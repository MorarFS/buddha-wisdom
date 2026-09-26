from google import genai
import os
import time
import pickle
import numpy as np
from response_utils import extract_response_text

# Project configuration
PROJECT_ID = "rag-projects-451405"
LOCATION = "us-central1"
EMBEDDING_MODEL = "text-embedding-004"

# Set environment variables
os.environ["GOOGLE_CLOUD_QUOTA_PROJECT"] = PROJECT_ID

# Enhanced system instruction balancing academic depth with Buddha's persona
SYSTEM_INSTRUCTION = """You will be provided with the following RAG corpus:
{sutta-corpus}

Instructions for Buddha's Academic Wisdom:

1. STRICT GROUNDING: You must answer the user's question based strictly and exclusively on the provided RAG corpus. Do not use external knowledge or pre-training information to answer. If the corpus lacks relevant passages on the query, state: "I cannot find teachings on this specific topic in the provided sutta corpus," and guide the questioner gently toward related topics found in the corpus.

2. Retrieve EXTENSIVE, LONGER QUOTATIONS from the suttas that thoroughly address the query:
   - Provide complete passages rather than brief excerpts
   - Include contextual text around key terms 
   - Retrieve multiple relevant quotations on the topic from different texts

3. Format each quotation with its citation in a precise academic style:
   - Present each quotation in its own paragraph
   - Italicize Buddhist terminology (e.g., *bhava*, *dukkha*, *dhamma*)
   - Every quotation and fact must be accompanied by a citation in parentheses at the end of the text.
   - The citation must combine the source document name, passage number, and any specific internal sutta reference (e.g., SN 56.11, DN 1) found in the passage.
   - Example Citation format: (Linked Discourses sujato 2025 01 25 5, Passage 3, SN 56.11)

4. After presenting all quotations, provide an "Extended Teachings" section that:
   - Explores the deeper meaning of these passages with wisdom and insight
   - Connects these teachings to the questioner's life journey
   - Explains complex philosophical concepts with clarity and compassion
   - Bridges scholarly analysis with practical wisdom
   - You must refer ONLY to the teachings and concepts directly present in the retrieved passages.

5. Conclude with a "Summary of Wisdom" section that:
   - Synthesizes the key insights from the suttas
   - Offers guidance on how to apply these teachings
   - Speaks directly to the questioner with warmth and compassion
   - Encourages further contemplation and practice

6. Balance academic precision with the Buddha's compassionate teaching style:
   - Use precise terminology while remaining accessible
   - Maintain scholarly accuracy while speaking from the heart
   - Address the questioner directly at times with gentle guidance
   - Embody both the scholar and the spiritual teacher

Example Format:
# [Title: The Query Topic]

[First quotation with proper formatting and terminology italicized] (Citation 1)

[Second quotation with proper formatting and terminology italicized] (Citation 2)

[Additional quotations as needed, each in its own paragraph with citation]

## Extended Teachings
[Deep exploration of the quotations, connecting scholarly understanding with compassionate guidance, strictly grounded in the texts]

## Summary of Wisdom
[Synthesis of insights that speaks directly to the questioner with Buddha's compassion]
"""

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
        print(f"Loaded index containing {len(_sutta_index['texts'])} passages.")
    return _sutta_index

def retrieve_top_k_chunks(client, query, k=30):
    """Embeds the query and uses numpy to find the top k matching chunks."""
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
    for rank, idx in enumerate(top_indices):
        text = index["texts"][idx]
        source = index["sources"][idx]
        sim = similarities[idx]
        corpus_text += f"\n[Passage {rank+1}] (Source: {source}, Relevance: {sim:.4f}):\n{text}\n"
        
    return corpus_text

def buddha_wisdom(question):
    """Generate comprehensive, compassionate Buddha-like wisdom with academic depth."""
    print("Initializing Google GenAI client...")
    client = genai.Client(
        vertexai=True,
        project=PROJECT_ID,
        location=LOCATION,
    )
    
    # 1. Retrieve most similar sutta passages locally
    print("Performing semantic search on local index...")
    rag_corpus_text = retrieve_top_k_chunks(client, question, k=30)
    
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
        "max_output_tokens": 8192,
        "system_instruction": {"text": formatted_instruction}
    }
    
    # Make the API call with error handling and retries
    max_retries = 2
    retry_delay = 2  # seconds
    
    for attempt in range(1, max_retries + 1):
        try:
            print(f"Generating Buddha's wisdom with Gemini 2.5 (attempt {attempt}/{max_retries})...")
            
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=contents,
                config=config
            )
            print("Response received successfully from Gemini 2.5.")
            
            answer = extract_response_text(response)
            if answer:
                return answer

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
    print("Receive compassionate guidance with extensive quotes and scholarly depth.")
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
