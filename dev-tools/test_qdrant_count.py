from qdrant_client import QdrantClient
import sys

try:
    client = QdrantClient(host="localhost", port=6333)
    count = client.count(collection_name="user_knowledge")
    print(f"Points in user_knowledge: {count.count}")
    
    count_mem = client.count(collection_name="nexe_chat_memory")
    print(f"Points in nexe_chat_memory: {count_mem.count}")
except Exception as e:
    print(f"Error: {e}")
    sys.exit(1)
