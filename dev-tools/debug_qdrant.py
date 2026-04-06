from qdrant_client import QdrantClient
import qdrant_client

print(f"File: {qdrant_client.__file__}")
try:
    print(f"Version: {qdrant_client.__version__}")
except AttributeError:
    print("Version: NOT FOUND")

client = QdrantClient(':memory:')
print(f"Client type: {type(client)}")
print(f"Has 'search': {'search' in dir(client)}")
print(f"Has 'query_points': {'query_points' in dir(client)}")

if 'query_points' in dir(client):
    try:
        client.create_collection("test_col", vectors_config={"size": 4, "distance": "Cosine"})
        client.upsert("test_col", points=[{"id": 1, "vector": [0.1, 0.2, 0.3, 0.4], "payload": {"val": 10}}])
        res = client.query_points("test_col", query=[0.1, 0.2, 0.3, 0.4], limit=1)
        print(f"Query result type: {type(res)}")
        print(f"Query points: {res.points if hasattr(res, 'points') else 'NO POINTS ATTR'}")
    except Exception as e:
        print(f"Query points test failed: {e}")
print(f"Attributes: {sorted([a for a in dir(client) if not a.startswith('_')])}")
