# /home/stefan_morar/gopath/vertex_init.py
import vertexai
from vertexai import rag  # Import the stable module

PROJECT_ID = "rag-projects-451405"  # Replace with your project ID
LOCATION = "us-central1"  # Or your desired location
BUCKET_NAME = "suttacentral"  # Replace with your bucket name

vertexai.init(project=PROJECT_ID, location=LOCATION)

print(f"Vertex AI initialized for project: {PROJECT_ID} in location: {LOCATION}")

# Configure embedding model
embedding_model_config = rag.RagEmbeddingModelConfig(
    vertex_prediction_endpoint=rag.VertexPredictionEndpoint(
        publisher_model="publishers/google/models/text-embedding-005"
    )
)

# Function to create the RagCorpus
def create_rag_corpus(corpus_display_name):
    """Creates a RagCorpus with the specified display name."""
    rag_corpus = rag.create_corpus(
        display_name=corpus_display_name,
        backend_config=rag.RagVectorDbConfig(
            rag_embedding_model_config=embedding_model_config
        ),
    )
    return rag_corpus
