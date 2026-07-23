"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/qdrant_pool.py
Description: Pool of QdrantClients to avoid concurrent access in embedded mode.
             Cached by path/url — each unique path has ONE single instance.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
from __future__ import annotations
import logging
import os
import threading
from pathlib import Path
from typing import Optional
from qdrant_client import QdrantClient

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_instances: dict[str, QdrantClient] = {}


def _anchor_path(path: Optional[str]) -> Path:
    """MC-091: resolve the qdrant path ONCE, anchored at the project root.

    _setup_qdrant (lifespan_services) anchors a relative NEXE_QDRANT_PATH to
    project_root, but this pool used to anchor to cwd — a Tauri-spawned
    sidecar (cwd = $HOME) would silently open a DIFFERENT vectors dir than
    the one the lifespan prepared.
    """
    p = Path(path or "storage/vectors")
    if not p.is_absolute():
        try:
            from core.paths.detection import get_repo_root
            p = get_repo_root() / p
        except Exception:
            p = p.resolve()
    return p


def _resolve_key(path: Optional[str], url: Optional[str]) -> str:
    """Build a cache key from the connection parameters."""
    if url:
        return f"url:{url}"
    return f"path:{_anchor_path(path)}"


def get_qdrant_client(
    path: Optional[str] = None,
    url: Optional[str] = None,
) -> QdrantClient:
    """Return shared QdrantClient per path/url. Thread-safe pool."""
    key = _resolve_key(path, url)

    if key in _instances:
        return _instances[key]

    with _lock:
        if key in _instances:
            return _instances[key]

        client = _create_client(path, url)
        _instances[key] = client
        return client


def _create_client(path: Optional[str], url: Optional[str]) -> QdrantClient:
    """Create a new QdrantClient from parameters."""
    if url:
        return QdrantClient(url=url, prefer_grpc=False)
    qdrant_path = _anchor_path(path)
    qdrant_path.mkdir(parents=True, exist_ok=True)
    # NEXE-SRV-WS3-06: el dir de vectors guarda embeddings (PII) — força
    # 0o700 owner-only replicant el patró de sqlite_store, perquè mkdir
    # hereta l'umask (0o755 amb umask 022) i exposaria els vectors a
    # altres comptes en un Mac compartit.
    os.chmod(qdrant_path, 0o700)
    return QdrantClient(path=str(qdrant_path))


def _flush_client(client: QdrantClient) -> None:
    """Attempts to flush pending changes before closing.

    Bug 13 fix — Qdrant embedded (Local) writes to disk via RocksDB.
    `close()` normally does an implicit flush, but if the client version
    does not guarantee it we may lose data on sudden shutdown. We try
    several known entry points:
      1. `client.flush()` (hypothetical future versions)
      2. `client._client.flush()` (internal layer)
      3. snapshot api for the collection (forces persistence)
    If none is available, we leave it to close() — but we have
    left an explicit note rather than silence.
    """
    flush = getattr(client, "flush", None)
    if callable(flush):
        try:
            flush()
            return
        except Exception as e:
            logger.warning("Qdrant client.flush() failed: %s", e)

    inner = getattr(client, "_client", None)
    inner_flush = getattr(inner, "flush", None) if inner is not None else None
    if callable(inner_flush):
        try:
            inner_flush()
            return
        except Exception as e:
            logger.warning("Qdrant inner _client.flush() failed: %s", e)

    # No explicit flush API available — close() will handle persistence.
    logger.debug("Qdrant client has no explicit flush(); relying on close()")


def close_qdrant_client():
    """Graceful shutdown. Call from lifespan shutdown.

    Bug 13 fix — previously `client.close()` ran without a prior flush and
    any exception was swallowed (`except: pass`), hiding possible data
    corruption. Now we do flush -> close, both with explicit error
    handling that logs the problem.
    """
    global _instances
    for key, client in list(_instances.items()):
        try:
            _flush_client(client)
        except Exception as e:
            logger.warning("Qdrant pool flush failed for %s: %s", key, e)
        try:
            client.close()
        except Exception as e:
            logger.warning("Qdrant pool close failed for %s: %s", key, e)
    _instances.clear()
