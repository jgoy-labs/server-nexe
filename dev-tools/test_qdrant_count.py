from qdrant_client import QdrantClient
import sys
from personality.i18n.resolve import t_modular


def _t(key: str, fallback: str, **kwargs) -> str:
    return t_modular(f"dev_tools.qdrant_count.{key}", fallback, **kwargs)

try:
    client = QdrantClient(host="localhost", port=6333)
    count = client.count(collection_name="user_knowledge")
    print(_t("user_knowledge", "Points in user_knowledge: {count}", count=count.count))
    
    count_mem = client.count(collection_name="nexe_chat_memory")
    print(_t("chat_memory", "Points in nexe_chat_memory: {count}", count=count_mem.count))
except Exception as e:
    print(_t("error", "Error: {error}", error=e))
    sys.exit(1)
