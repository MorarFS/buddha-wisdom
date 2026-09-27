import os
import pickle
import time
import numpy as np
from pypdf import PdfReader
from tqdm import tqdm
from google import genai
from concurrent.futures import ThreadPoolExecutor, as_completed

# Configuration (matching the project credentials and setup)
PROJECT_ID = "rag-projects-451405"
LOCATION = "us-central1"
EMBEDDING_MODEL = "text-embedding-004"
PDF_DIR = "../data/suttacentral/"
INDEX_FILE = "sutta_index.pkl"

# Chunking configuration
CHUNK_SIZE = 1200      # characters (~200-300 words)
CHUNK_OVERLAP = 200    # characters

# Parallel execution settings
BATCH_SIZE = 30        # Safely below the 20,000 token limit
MAX_WORKERS = 5        # Number of concurrent threads calling Vertex AI

def extract_chunks_from_pdf(pdf_path):
    """Extracts text chunks from a PDF file and retains source filename metadata."""
    filename = os.path.basename(pdf_path)
    # Clean up the file suffix for readable citations
    citation_source = filename.replace(".pdf", "").replace("-", " ")
    
    print(f"Reading: {filename}...")
    reader = PdfReader(pdf_path)
    
    # Extract text from all pages
    full_text = []
    for i, page in enumerate(reader.pages):
        text = page.extract_text()
        if text:
            full_text.append(text)
            
    document_text = "\n".join(full_text)
    
    # Simple sliding window chunker
    chunks = []
    start = 0
    while start < len(document_text):
        end = start + CHUNK_SIZE
        chunk_text = document_text[start:end].strip()
        if len(chunk_text) > 100:  # Ignore very small trailing fragments
            chunks.append({
                "text": chunk_text,
                "source": citation_source
            })
        start += (CHUNK_SIZE - CHUNK_OVERLAP)
        
    return chunks

def build_index():
    # Initialize the GenAI client with Vertex AI mode enabled
    print(f"Initializing Google GenAI client (Vertex AI in {LOCATION})...")
    client = genai.Client(
        vertexai=True,
        project=PROJECT_ID,
        location=LOCATION,
    )
    
    # 1. Scan for PDFs
    if not os.path.exists(PDF_DIR):
        print(f"Error: PDF directory {PDF_DIR} does not exist.")
        return
        
    pdf_files = [os.path.join(PDF_DIR, f) for f in os.listdir(PDF_DIR) if f.lower().endswith(".pdf")]
    print(f"Found {len(pdf_files)} PDF files to index.")
    
    # 2. Extract chunks from all PDFs
    all_chunks = []
    for pdf_file in pdf_files:
        try:
            chunks = extract_chunks_from_pdf(pdf_file)
            all_chunks.extend(chunks)
            print(f"  Extracted {len(chunks)} chunks.")
        except Exception as e:
            print(f"  Error reading {pdf_file}: {e}")
            
    print(f"\nTotal extracted chunks across all documents: {len(all_chunks)}")
    if not all_chunks:
        print("No chunks found. Exiting.")
        return
        
    # 3. Generate embeddings in batches concurrently
    texts = [c["text"] for c in all_chunks]
    sources = [c["source"] for c in all_chunks]
    
    # Prepare batch inputs with their respective start indices
    batches = []
    for i in range(0, len(texts), BATCH_SIZE):
        batches.append((i, texts[i:i+BATCH_SIZE]))
        
    embeddings_dict = {}
    
    print(f"\nGenerating embeddings using {EMBEDDING_MODEL} (batch size={BATCH_SIZE}, threads={MAX_WORKERS})...")
    
    def embed_batch(batch_info):
        idx, batch_texts = batch_info
        # Try up to 3 times with exponential backoff on failure
        for attempt in range(3):
            try:
                response = client.models.embed_content(
                    model=EMBEDDING_MODEL,
                    contents=batch_texts
                )
                return idx, [emb.values for emb in response.embeddings]
            except Exception as e:
                if attempt < 2:
                    wait_time = 2 * (attempt + 1)
                    time.sleep(wait_time)
                else:
                    raise e

    # Execute concurrent requests using a thread pool
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(embed_batch, b): b for b in batches}
        
        # Display progress using tqdm
        for future in tqdm(as_completed(futures), total=len(futures), desc="Embedding progress"):
            try:
                idx, values = future.result()
                embeddings_dict[idx] = values
            except Exception as e:
                print(f"\nFailed to embed batch: {e}")
                # Cancel pending futures on failure
                for f in futures:
                    f.cancel()
                raise e

    # Reassemble the embeddings list in the correct order
    print("\nReassembling embeddings...")
    embeddings_list = []
    for i in range(0, len(texts), BATCH_SIZE):
        embeddings_list.extend(embeddings_dict[i])
        
    # 4. Save to disk
    print("Converting vectors to numpy array...")
    embeddings_arr = np.array(embeddings_list, dtype=np.float32)
    
    print(f"Index shape: {embeddings_arr.shape}")
    
    index_data = {
        "texts": texts,
        "sources": sources,
        "embeddings": embeddings_arr,
        "chunk_stride": CHUNK_SIZE - CHUNK_OVERLAP,
    }
    
    print(f"Saving index to {INDEX_FILE}...")
    with open(INDEX_FILE, "wb") as f:
        pickle.dump(index_data, f)
        
    print("Indexing completed successfully!")

if __name__ == "__main__":
    build_index()
