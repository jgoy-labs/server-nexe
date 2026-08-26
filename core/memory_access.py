"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/memory_access.py
Description: D-M memory porter. Plugins receive a filtered view, never MemoryAPI.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Sequence

logger = logging.getLogger(__name__)

# Canonical names for the three collections server-nexe ships with. #896:
# these were 75 independent literals across 22 files (some spelling
# "personal_memory" a fourth time as a fresh string); this is the one place
# that spells them. Import these instead of writing the literal again.
DOCS_COLLECTION = "nexe_documentation"
KNOWLEDGE_COLLECTION = "user_knowledge"
MEMORY_COLLECTION = "personal_memory"

# Last-resort names when list_collections() is empty or unusable. A new
# collection created through the API becomes visible via list_collections;
# these three only cover the case where discovery itself failed (B2). Order
# matches the pre-#896 literal lists (docs, memory, knowledge) — some callers
# (e.g. tests/test_rag_empty_collections_mc041_mc046.py) assert this order.
SYSTEM_COLLECTIONS = (DOCS_COLLECTION, MEMORY_COLLECTION, KNOWLEDGE_COLLECTION)

_REPO_ROOT = Path(__file__).resolve().parent.parent

# Vector width of the default embedding model. It lives HERE, in core, and not
# imported from memory/, because core/endpoints/chat_memory.py needs it at
# import time and that import is reached from create_app() — pulling
# memory.memory.constants in loads MemoryModule, MemoryAPI and the whole
# embeddings package, so a broken memory/ left the product with NO server at
# all (#888). memory/ is DEGRADABLE by decision: the chat must come up without
# it. The canonical declaration is still memory/embeddings/constants.py; the
# two are pinned together by tests/core/test_vector_size_anchor.py, which
# fails if they ever drift apart.
DEFAULT_VECTOR_SIZE = 768


class CollectionDenied(PermissionError):
    """Plugin asked to use a collection the view (or the manager) has closed."""

    def __init__(self, plugin_id: str, collection: str) -> None:
        super().__init__(
            f"plugin {plugin_id!r} cannot use collection {collection!r}"
        )
        self.plugin_id = plugin_id
        self.collection = collection


class MemoryView:
    """Filtered facade over a MemoryAPI. Default is access to everything.

    Denied collections are dropped from search/list and rejected on writes.
    ``close()`` is not forwarded — the client is shared (B1).
    """

    def __init__(
        self,
        api: Any,
        *,
        plugin_id: str,
        denied: frozenset[str] = frozenset(),
    ) -> None:
        self._api = api
        self.plugin_id = plugin_id
        self._denied = denied

    @property
    def ingest_config(self) -> Any:
        return getattr(self._api, "ingest_config", None)

    def filter_requested(self, requested: Sequence[str]) -> list[str]:
        return [c for c in requested if isinstance(c, str) and c not in self._denied]

    async def visible_names(self) -> list[str]:
        names = self._listed_names(await self._try_list())
        if not names:
            names = list(SYSTEM_COLLECTIONS)
        return [n for n in names if n not in self._denied]

    def _require(self, name: str) -> str:
        if name in self._denied:
            raise CollectionDenied(self.plugin_id, name)
        return name

    async def _try_list(self) -> Any:
        try:
            return await self._api.list_collections()
        except Exception:
            return None

    @staticmethod
    def _listed_names(infos: Any) -> list[str]:
        if not isinstance(infos, (list, tuple)):
            return []
        names: list[str] = []
        for info in infos:
            name = getattr(info, "name", None)
            if isinstance(name, str) and name:
                names.append(name)
        return names

    async def list_collections(self) -> list[Any]:
        infos = await self._try_list()
        if not isinstance(infos, (list, tuple)):
            return []
        return [
            info for info in infos
            if getattr(info, "name", None) not in self._denied
        ]

    async def collection_exists(self, name: str) -> bool:
        if name in self._denied:
            return False
        return await self._api.collection_exists(name)

    async def create_collection(self, name: str, *args: Any, **kwargs: Any) -> Any:
        return await self._api.create_collection(self._require(name), *args, **kwargs)

    async def delete_collection(self, name: str) -> Any:
        return await self._api.delete_collection(self._require(name))

    async def store(self, text: str, collection: str, *args: Any, **kwargs: Any) -> Any:
        return await self._api.store(text, self._require(collection), *args, **kwargs)

    async def store_batch(self, items: Any, collection: str, *args: Any, **kwargs: Any) -> Any:
        return await self._api.store_batch(items, self._require(collection), *args, **kwargs)

    async def store_batch_precomputed(
        self, items: Any, embeddings: Any, collection: str, *args: Any, **kwargs: Any
    ) -> Any:
        return await self._api.store_batch_precomputed(
            items, embeddings, self._require(collection), *args, **kwargs
        )

    async def search(self, query: str, collection: str, *args: Any, **kwargs: Any) -> Any:
        return await self._api.search(query, self._require(collection), *args, **kwargs)

    async def embed_query(self, text: str) -> Any:
        return await self._api.embed_query(text)

    async def get(self, doc_id: str, collection: str, *args: Any, **kwargs: Any) -> Any:
        return await self._api.get(doc_id, self._require(collection), *args, **kwargs)

    async def delete(self, doc_id: str, collection: str, *args: Any, **kwargs: Any) -> Any:
        return await self._api.delete(doc_id, self._require(collection), *args, **kwargs)

    async def scroll(self, collection: str, *args: Any, **kwargs: Any) -> Any:
        return await self._api.scroll(self._require(collection), *args, **kwargs)

    async def count(self, collection: str) -> Any:
        return await self._api.count(self._require(collection))

    async def forget_everything(self, user_id: str = "default") -> Dict[str, int]:
        """Wipe the MemoryService stores for ``user_id`` (#897).

        The door exists because a plugin may not import memory/ at all (D-M),
        not even deferred — and without it "clear all memory" could only reach
        the RAG collection, leaving every fact MemoryService had stored while
        telling the user nothing was left.

        Returns an empty dict when the service is not running: the caller must
        be able to tell "nothing to wipe" from "wiped nothing", and reporting a
        clean sweep that never happened is the bug this fixes.
        """
        try:
            from memory.memory.module import get_memory_service
        except ImportError:
            return {}
        svc = get_memory_service()
        if svc is None or not getattr(svc, "initialized", False):
            return {}
        return await svc.forget_everything(user_id)

    async def cleanup_expired(self, collection: str) -> Any:
        return await self._api.cleanup_expired(self._require(collection))


def resolve_memory_policy(plugin_id: str) -> frozenset[str]:
    """Union of the plugin's declared deny and the manager veto. Deny always wins."""
    return _manifest_deny(plugin_id) | _manager_deny(plugin_id)


def _manifest_deny(plugin_id: str) -> frozenset[str]:
    path = _REPO_ROOT / "plugins" / plugin_id / "manifest.toml"
    data = _read_toml(path)
    module = data.get("module") if isinstance(data.get("module"), dict) else {}
    memory = module.get("memory") if isinstance(module.get("memory"), dict) else {}
    return _deny_set(memory.get("deny"))


def _manager_deny(plugin_id: str) -> frozenset[str]:
    cfg = _loaded_config()
    plugins = cfg.get("plugins") if isinstance(cfg.get("plugins"), dict) else {}
    access = plugins.get("memory_access") if isinstance(plugins.get("memory_access"), dict) else {}
    plugin_pol = access.get(plugin_id) if isinstance(access.get(plugin_id), dict) else {}
    return _deny_set(plugin_pol.get("deny"))


def _deny_set(raw: Any) -> frozenset[str]:
    if not isinstance(raw, (list, tuple)):
        return frozenset()
    return frozenset(x for x in raw if isinstance(x, str) and x)


def _read_toml(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        import tomllib
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    except Exception as exc:
        logger.debug("memory policy: cannot read %s: %s", path, exc)
        return {}
    return data if isinstance(data, dict) else {}


def _loaded_config() -> Dict[str, Any]:
    try:
        from core.server_state import get_server_state
        cfg = getattr(get_server_state(), "config", None)
    except Exception:
        return {}
    return cfg if isinstance(cfg, dict) else {}


async def get_memory_view(
    plugin_id: str,
    *,
    api: Any = None,
    extra_deny: Optional[Iterable[str]] = None,
) -> MemoryView:
    """The only door plugins should use to reach memory collections."""
    if api is None:
        from memory.memory.api.v1 import get_memory_api
        api = await get_memory_api()
    denied = resolve_memory_policy(plugin_id)
    if extra_deny is not None:
        denied = denied | _deny_set(list(extra_deny))
    return MemoryView(api, plugin_id=plugin_id, denied=denied)
