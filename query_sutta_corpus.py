from google import genai
import os
import time
import pickle
import numpy as np
from response_utils import (
    add_pdf_page_citations,
    extract_response_text,
    quotations_are_grounded,
)
from source_pages import infer_pdf_page_ranges

# Project configuration
PROJECT_ID = "rag-projects-451405"
LOCATION = "us-central1"
GENERATION_LOCATION = "global"
GENERATION_MODEL = "gemini-3.1-flash-lite"
EMBEDDING_MODEL = "text-embedding-004"

# Set environment variables
os.environ["GOOGLE_CLOUD_QUOTA_PROJECT"] = PROJECT_ID

# The original passage-first format, with explicit rules against invented citations.
SYSTEM_INSTRUCTION = """Answer the question using only the Theravada sutta passages below.
{sutta-corpus}

Use this structure:

# [A short title for the question]

## Passages from the Suttas
Give two or three substantial, relevant quotations, preferably from different
suttas. Present each quotation in its own blockquote. Copy contiguous text from
the supplied passages word for word. You may join PDF line wraps and repair
line-end hyphenation, but do not paraphrase or add words inside a quotation.
Choose complete sentences with enough context to understand them. Never extend
a quotation beyond the supplied passage or repeat near-identical passages.

Immediately after every blockquote, write a separate citation line in this form:
**Source:** [the full Source name supplied above]; **Retrieved passage:**
[the Passage number supplied above]; **Sutta page:** [SN 56.11](https://suttacentral.net/sn56.11/en/sujato).
Copy the full Source name exactly. The Passage number is a search-result label,
not a canonical sutta number. Include the linked Sutta page only when the
internal sutta reference is clear from the quoted passage. If the reference
is unclear, omit the Sutta page field. The app adds verified PDF page numbers
after generation, so do not supply PDF page numbers yourself. Never cite only
a Passage number. Do not guess a sutta reference, quotation, or citation.

## Extended Teachings
Analyze what the quoted passages say and how they relate to the question.
Explain Buddhist terms in plain language. Distinguish the text's claims from
your interpretation. Base every substantive claim on the cited passages.
Speak with scholarly care and compassion, without impersonating the Buddha.
Avoid em dashes in your own prose; preserve punctuation inside quotations.

## Summary of Wisdom
Conclude with a concise synthesis and practical reflection grounded in the
quoted passages. Address the questioner directly when it feels natural.

If the retrieved passages do not support an answer, say that you cannot find
a teaching on this topic in the provided sutta corpus. Do not fill gaps from
memory. Use clear, natural prose."""


# Global variable to cache the index in memory
_sutta_index = None

def get_sutta_index():
    """Loads the local RAG index into memory once."""
    global _sutta_index
    if _sutta_index is None:
        index_path = os.path.join(os.path.dirname(__file__), "sutta_index.pkl")
        print(f"Loading local Sutta Index from {index_path}...")
        if not os.path.exists(index_path):
            raise FileNotFoundError(f"Index file not found at {index_path}. Please run create_local_index.py first.")
        with open(index_path, "rb") as f:
            _sutta_index = pickle.load(f)
        _sutta_index["pdf_page_ranges"] = infer_pdf_page_ranges(_sutta_index)
        print(f"Loaded index containing {len(_sutta_index['texts'])} passages.")
    return _sutta_index

def retrieve_top_k_chunks(client, query, k=8):
    """Return retrieved text and verified PDF page ranges by result rank."""
    index = get_sutta_index()
    
    # 1. Embed query
    response = client.models.embed_content(
        model=EMBEDDING_MODEL,
        contents=query
    )
    query_vector = np.array(response.embeddings[0].values, dtype=np.float32)
    
    # Normalize query vector for cosine similarity
    query_norm = np.linalg.norm(query_vector)
    if query_norm > 0:
        query_vector = query_vector / query_norm
        
    # 2. Compute similarity (dot product on normalized vectors is cosine similarity)
    similarities = np.dot(index["embeddings"], query_vector)
    
    # 3. Get top k matching indices
    top_indices = np.argsort(similarities)[::-1][:k]
    
    # 4. Construct corpus text block and collect citations
    corpus_text = ""
    pages_by_passage = {}
    for rank, idx in enumerate(top_indices):
        text = index["texts"][idx]
        source = index["sources"][idx]
        sim = similarities[idx]
        corpus_text += f"\n[Passage {rank+1}] (Source: {source}, Relevance: {sim:.4f}):\n{text}\n"
        pages = index["pdf_page_ranges"][idx]
        if pages:
            pages_by_passage[rank + 1] = pages
        
    return corpus_text, pages_by_passage

def buddha_wisdom(question):
    """Generate quoted sutta passages followed by analysis and a summary."""
    print("Initializing Google GenAI client...")
    embedding_client = genai.Client(
        vertexai=True,
        project=PROJECT_ID,
        location=LOCATION,
    )
    
    # 1. Retrieve most similar sutta passages locally
    print("Performing semantic search on local index...")
    rag_corpus_text, pages_by_passage = retrieve_top_k_chunks(
        embedding_client, question, k=8
    )
    generation_client = genai.Client(
        vertexai=True,
        project=PROJECT_ID,
        location=GENERATION_LOCATION,
    )
    
    # 2. Inject RAG corpus text into system instructions
    formatted_instruction = SYSTEM_INSTRUCTION.replace("{sutta-corpus}", rag_corpus_text)
    
    # 3. Setup prompt payload
    contents = [{
        "role": "user",
        "parts": [{"text": question}]
    }]
    
    # 4. Configure generation
    config = {
        "temperature": 0.25,
        "top_p": 0.95,
        "max_output_tokens": 2048,
        "system_instruction": {"text": formatted_instruction}
    }
    
    # Make the API call with error handling and retries
    max_retries = 2
    retry_delay = 2  # seconds
    
    for attempt in range(1, max_retries + 1):
        try:
            print(f"Generating Buddha's wisdom with Gemini 3.1 Flash-Lite (attempt {attempt}/{max_retries})...")
            
            response = generation_client.models.generate_content(
                model=GENERATION_MODEL,
                contents=contents,
                config=config
            )
            print("Response received successfully from Gemini 3.1 Flash-Lite.")
            
            answer = extract_response_text(response)
            unsupported_topic = (
                answer
                and "cannot find" in answer.lower()
                and "sutta corpus" in answer.lower()
                and ">" not in answer
            )
            if answer and (unsupported_topic or quotations_are_grounded(answer, rag_corpus_text)):
                return add_pdf_page_citations(answer, pages_by_passage)

            if answer:
                raise RuntimeError("Gemini returned an unsupported quotation or citation")

            reasons = [
                str(candidate.finish_reason)
                for candidate in (getattr(response, "candidates", None) or [])
            ]
            raise RuntimeError(f"Gemini returned no answer (finish reasons: {reasons})")
                
        except Exception as e:
            print(f"Error generating content (attempt {attempt}/{max_retries}): {e}")
            if attempt < max_retries:
                print(f"Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
                retry_delay *= 2  # Exponential backoff
            else:
                raise

def main():
    """Interactive Buddha wisdom session with academic depth."""
    # Clear the terminal for better readability
    os.system('cls' if os.name == 'nt' else 'clear')
    
    print("\n" + "═" * 80)
    print("🪷  BUDDHA'S WISDOM WITH CITATIONS (LOCAL RAG)  🪷")
    print("═" * 80)
    print("\nSeek wisdom through questions about dharma, suffering, enlightenment, and more.")
    print("Receive clear guidance grounded in cited sutta passages.")
    print("Type 'exit' to end your session.\n")
    
    # Warm up index loading
    try:
        get_sutta_index()
    except Exception as e:
        print(f"Error loading index on startup: {e}")
        return
        
    while True:
        question = input("\n👤 Your question: ")
        if question.lower() in ["exit", "quit", "bye"]:
            print("\n🪷 May you walk the path with mindfulness and find peace. 🪷\n")
            break
        
        print("\n🪷 Seeking wisdom in the suttas...\n")
        answer = buddha_wisdom(question)
        print("\n" + "─" * 80)
        print(answer)
        print("─" * 80)

if __name__ == "__main__":
    main()
