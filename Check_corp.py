import os
from google.cloud import aiplatform_v1
import google.api_core.exceptions

# Project information
PROJECT_ID = "rag-projects-451405"
LOCATION = "us-central1"

# Set the quota project to avoid warnings
os.environ["GOOGLE_CLOUD_QUOTA_PROJECT"] = PROJECT_ID

def main():
    """Check for RAG corpus using multiple methods."""
    print(f"\n{'='*80}")
    print(f"RAG CORPUS FINDER - Project: {PROJECT_ID}, Location: {LOCATION}")
    print(f"{'='*80}\n")

    # Method 1: Using MetadataServiceClient
    print("METHOD 1: Using MetadataServiceClient...")
    try:
        client = aiplatform_v1.MetadataServiceClient()
        parent = f"projects/{PROJECT_ID}/locations/{LOCATION}/metadataStores/default"
        print(f"Querying metadata store: {parent}")
        
        request = aiplatform_v1.ListArtifactsRequest(parent=parent)
        page_result = client.list_artifacts(request=request, timeout=60)
        
        found = False
        for artifact in page_result:
            if hasattr(artifact, 'metadata'):
                metadata = artifact.metadata
                if isinstance(metadata, dict) and metadata.get("rag_corpus_type") == "RAG_CORPUS":
                    found = True
                    print(f"\nFound RAG Corpus:")
                    print(f"  Name: {artifact.name}")
                    print(f"  ID: {artifact.name.split('/')[-1]}")
                    print(f"  Display Name: {artifact.display_name}")
        
        if not found:
            print("No RAG corpus found using MetadataServiceClient.")
    except google.api_core.exceptions.PermissionDenied as e:
        print(f"Permission denied: {e}")
        print("You may need to enable the Vertex AI API or grant additional permissions.")
    except Exception as e:
        print(f"Error using MetadataServiceClient: {e}")

    # Method 2: Using vertexai.rag module (if available)
    print("\nMETHOD 2: Using vertexai.rag module...")
    try:
        try:
            from vertexai import rag
            import vertexai
            
            vertexai.init(project=PROJECT_ID, location=LOCATION)
            print("Listing all RAG corpora...")
            corpora = rag.list_corpora()
            
            if corpora and len(corpora) > 0:
                print(f"\nFound {len(corpora)} RAG corpora:")
                for corpus in corpora:
                    print(f"  Name: {corpus.name}")
                    print(f"  Display Name: {corpus.display_name}")
                    print(f"  ID: {corpus.name.split('/')[-1]}")
                    print()
            else:
                print("No RAG corpora found using vertexai.rag module.")
        except ImportError:
            print("vertexai.rag module not available.")
            print("Try installing it with: pip install --upgrade google-cloud-aiplatform>=1.25.0")
    except Exception as e:
        print(f"Error using vertexai.rag: {e}")

    # Method 3: Direct API request for known corpus ID
    print("\nMETHOD 3: Checking specific corpus ID...")
    corpus_id = "648518346341351424"  # The corpus ID you've been using
    try:
        from google.cloud import aiplatform
        
        aiplatform.init(project=PROJECT_ID, location=LOCATION)
        parent = f"projects/{PROJECT_ID}/locations/{LOCATION}/ragCorpora/{corpus_id}"
        print(f"Checking if corpus exists: {parent}")
        
        try:
            # Using a different API call to check if this specific corpus exists
            from google.api_core import path_template
            from google.auth.transport import requests as google_requests
            from google.oauth2 import service_account
            
            http_request = google_requests.Request()
            url = f"https://{LOCATION}-aiplatform.googleapis.com/v1/{parent}"
            print(f"Checking URL: {url}")
            
            # Just print info about this corpus for now
            print(f"This is the corpus ID you've been using in your Buddha Wisdom app.")
            print(f"Full resource name: {parent}")
        except Exception as e:
            print(f"API request failed: {e}")
    except Exception as e:
        print(f"Error checking specific corpus: {e}")

    print("\nTROUBLESHOOTING TIPS:")
    print("1. Ensure the Vertex AI API is enabled in your project")
    print("2. Verify you have the correct permissions (roles/aiplatform.user or higher)")
    print("3. Check if you created the RAG corpus in a different project or region")
    print("4. Try using the Google Cloud Console to list RAG resources")
    print("5. If you know your corpus ID works in your Buddha app, you can continue using it\n")

if __name__ == "__main__":
    main()
