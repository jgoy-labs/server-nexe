from qdrant_client import QdrantClient
import sys

try:
    client = QdrantClient(host="localhost", port=6333)
    collections = client.get_collections()
    print(f"Collections: {collections}")
except Exception as e:
    print(f"Error: {e}")
    sys.exit(1)
