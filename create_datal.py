import os
from google.cloud import storage
import traceback
from vertexai import rag
import vertexai

# Import the variables and function from vertex_init.py
try:
    from vertex_init import BUCKET_NAME, create_rag_corpus, PROJECT_ID, LOCATION
except ImportError:
    print("Error: Could not import BUCKET_NAME, create_rag_corpus, PROJECT_ID, or LOCATION from vertex_init.py.")
    print("Please ensure vertex_init.py is in the same directory or Python path and defines these elements.")
    exit(1)

def get_gcs_uris(bucket_name, prefix=None):
    """Lists GCS URIs for PDF files in a bucket."""
    if not bucket_name:
        raise ValueError("bucket_name must be provided (imported from vertex_init.py).")
    uris = []
    print(f"Scanning GCS bucket gs://{bucket_name}/ for PDF files" + (f" with prefix '{prefix}'." if prefix else "."))
    try:
        storage_client = storage.Client()
        bucket = storage_client.bucket(bucket_name)
        blobs = bucket.list_blobs(prefix=prefix)

        for blob in blobs:
            if blob.name.lower().endswith(".pdf"):
                if not blob.name.endswith('/'):
                    uri = f"gs://{bucket_name}/{blob.name}"
                    uris.append(uri)
                    print(f"  Found PDF URI: {uri}")

        if prefix and not uris:
             print(f"Warning: No PDF files found with prefix '{prefix}' in bucket gs://{bucket_name}/")
        elif not uris:
             print(f"Warning: No PDF files found in bucket gs://{bucket_name}/")

    except Exception as e:
        raise Exception(f"Error accessing GCS bucket gs://{bucket_name}/: {e}")
    return uris

# --- Main Execution ---
if __name__ == "__main__":
    try:
        # 1. Get GCS URIs of the PDF files
        pdf_uris = get_gcs_uris(BUCKET_NAME, prefix=None)
        print(f"\nFound {len(pdf_uris)} PDF URIs in GCS bucket '{BUCKET_NAME}'.")

        if not pdf_uris:
            print("No PDF files found to import. Exiting.")
        else:
            # 2. Create or Get the RagCorpus (get its resource name)
            corpus_display_name = "sutta-corpus"
            print(f"\nEnsuring RAG Corpus '{corpus_display_name}' exists...")
            rag_corpus_object = create_rag_corpus(corpus_display_name)
            corpus_resource_name = rag_corpus_object.name
            print(f"Using RAG Corpus: {corpus_resource_name}")

            # 3. Initialize the Vertex AI API
            print(f"\nInitializing Vertex AI SDK...")
            vertexai.init(project=PROJECT_ID, location=LOCATION)
            
            # 4. Import files using the high-level SDK
            print(f"Starting import operation using high-level Vertex AI SDK...")
            print(f"  Chunk Size: 500 tokens")
            print(f"  Chunk Overlap: 50 tokens")
            
            # Use the high-level rag.import_files method
            import_response = rag.import_files(
                corpus_name=corpus_resource_name,
                paths=pdf_uris,
                transformation_config=rag.TransformationConfig(
                    chunking_config=rag.ChunkingConfig(
                        chunk_size=500,
                        chunk_overlap=50
                    )
                ),
                max_embedding_requests_per_min=1000  # Optional rate limiter
            )
            
            print("\nImport operation completed.")
            # The high-level SDK returns imported_rag_files_count
            imported_count = getattr(import_response, 'imported_rag_files_count', 'N/A')
            print(f"Import results: {imported_count} file(s) processed successfully.")

    except ValueError as e:
        print(f"\nConfiguration Error: {e}")
    except ImportError as e:
        print(f"\nImport Error: {e}")
        print("Please ensure vertex_init.py is correctly set up.")
    except Exception as e:
        print(f"\nAn unexpected error occurred: {e}")
        print("\n--- Full Traceback ---")
        traceback.print_exc()
        print("--- End Traceback ---")
        
        # Provide troubleshooting guidance for common SDK issues
        print("\n--- Troubleshooting Tips ---")
        print("1. Check that your SDK version is up to date:")
        print("   pip install --upgrade google-cloud-aiplatform")
        print("2. Ensure you have the latest vertexai package:")
        print("   pip show vertexai")
        print("3. Verify your authentication is set up correctly:")
        print("   gcloud auth application-default login")
        print("4. Make sure the Vertex AI API is enabled in your project.")
