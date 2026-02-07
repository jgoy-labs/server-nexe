from qdrant_client import QdrantClient
import qdrant_client
from personality.i18n.resolve import t_modular


def _t(key: str, fallback: str, **kwargs) -> str:
    return t_modular(f"dev_tools.debug.{key}", fallback, **kwargs)


print(_t("file", "File: {path}", path=qdrant_client.__file__))
try:
    print(_t("version", "Version: {version}", version=qdrant_client.__version__))
except AttributeError:
    print(_t("version_not_found", "Version: NOT FOUND"))

client = QdrantClient(':memory:')
print(_t("client_type", "Client type: {client_type}", client_type=type(client)))
print(_t("has_search", "Has 'search': {value}", value='search' in dir(client)))
print(_t("has_query_points", "Has 'query_points': {value}", value='query_points' in dir(client)))

if 'query_points' in dir(client):
    try:
        client.create_collection("test_col", vectors_config={"size": 4, "distance": "Cosine"})
        client.upsert("test_col", points=[{"id": 1, "vector": [0.1, 0.2, 0.3, 0.4], "payload": {"val": 10}}])
        res = client.query_points("test_col", query=[0.1, 0.2, 0.3, 0.4], limit=1)
        print(_t("query_result_type", "Query result type: {result_type}", result_type=type(res)))
        print(_t(
            "query_points",
            "Query points: {points}",
            points=res.points if hasattr(res, 'points') else _t("no_points_attr", "NO POINTS ATTR"),
        ))
    except Exception as e:
        print(_t("query_points_failed", "Query points test failed: {error}", error=e))
print(_t(
    "attributes",
    "Attributes: {attributes}",
    attributes=sorted([a for a in dir(client) if not a.startswith('_')]),
))
