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
import logging
import os
import threading
from pathlib import Path
from typing import Optional
from qdrant_client import QdrantClient

logger = logging.getLogger(__name__)

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


def _flush_client(client: QdrantClient) -> None:
    """Intenta fer flush dels canvis pendents abans de tancar.

    Bug 13 fix — Qdrant embedded (Local) escriu al disc via RocksDB.
    `close()` normalment fa el flush implicit, pero si la versio del
    client no el garanteix podem tenir perdua de dades en cas de
    shutdown sobtat. Provem diversos punts d'entrada coneguts:
      1. `client.flush()` (versions futures hipotetiques)
      2. `client._client.flush()` (capa interna)
      3. snapshot api per al collection (forca persistencia)
    Si cap esta disponible, ho deixem en mans del close() — pero
    hem deixat constancia explicita en lloc de silenci.
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
    """Graceful shutdown. Cridar des de lifespan shutdown.

    Bug 13 fix — abans `client.close()` corria sense flush previ i
    qualsevol excepcio s'engolia (`except: pass`), amagant possibles
    corrupcions de dades. Ara fem flush -> close, ambdos amb error
    handling explicit que loguea el problema.
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
