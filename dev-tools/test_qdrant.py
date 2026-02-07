from qdrant_client import QdrantClient
import sys
from personality.i18n.resolve import t_modular


def _t(key: str, fallback: str, **kwargs) -> str:
    return t_modular(f"dev_tools.qdrant.{key}", fallback, **kwargs)

try:
    client = QdrantClient(host="localhost", port=6333)
    collections = client.get_collections()
    print(_t("collections", "Collections: {collections}", collections=collections))
except Exception as e:
    print(_t("error", "Error: {error}", error=e))
    sys.exit(1)
