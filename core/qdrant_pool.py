"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/qdrant_pool.py
Description: Pool de QdrantClients per evitar concurrent access a embedded mode.
             Cacheja per path/url — cada path unic te UNA sola instancia.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
from __future__ import annotations
import os
import threading
from pathlib import Path
from typing import Optional
from qdrant_client import QdrantClient

_lock = threading.Lock()
_instances: dict[str, QdrantClient] = {}


def _resolve_key(path: Optional[str], url: Optional[str]) -> str:
    """Build a cache key from the connection parameters."""
    if url:
        return f"url:{url}"
    resolved = str(Path(path or "storage/vectors").resolve())
    return f"path:{resolved}"


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
    qdrant_path = path or "storage/vectors"
    Path(qdrant_path).mkdir(parents=True, exist_ok=True)
    return QdrantClient(path=qdrant_path)


def close_qdrant_client():
    """Graceful shutdown. Cridar des de lifespan shutdown."""
    global _instances
    for key, client in list(_instances.items()):
        try:
            client.close()
        except Exception:
            pass
    _instances.clear()
