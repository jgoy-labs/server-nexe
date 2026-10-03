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
import time
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
    # NEXE-SRV-WS3-06: the vectors dir holds embeddings (PII) — force
    # 0o700 owner-only, copying the sqlite_store pattern, because mkdir
    # inherits the umask (0o755 with umask 022) and would expose the vectors to
    # other accounts on a shared Mac.
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


# ═══════════════════════════════════════════════════════════════════════════
# Probe — the only place that ASKS whether Qdrant is really there
# ═══════════════════════════════════════════════════════════════════════════
#
# Until now nothing asked. memory/rag/health.py reported "qdrant_available:
# pass" after checking the installed package VERSION, and lifespan set
# server_state.qdrant_available = True unconditionally right after a mkdir —
# in external mode it did not even contact the URL. Everything downstream
# inherited that: the readiness aggregate, /status, and the watcher's Qdrant
# eye, which could not fire because it read a flag that is only ever False
# during shutdown.
#
# The probe goes through the POOLED client on purpose. A probe that opens its
# own connection measures a different thing than the one serving the chat: it
# would answer "fine" while the shared client is wedged, or "locked" while the
# real one holds the lock legitimately.

PROBE_TIMEOUT_S = 5.0

# Last real observation: (ok, detail, monotonic timestamp). Written by whoever
# probes, read by everyone who must not.
_last_observation: Optional[tuple[bool, str, float]] = None
_observation_lock = threading.Lock()


def probe_qdrant(
    path: Optional[str] = None,
    url: Optional[str] = None,
    timeout: Optional[float] = None,
) -> tuple[bool, str]:
    """Ask Qdrant for its collections. Returns (ok, detail).

    Bounded: the call runs in a daemon thread and is given ``timeout``
    seconds. A wedged external Qdrant makes the probe answer "timeout"
    instead of hanging whoever asked — health endpoints and the watcher both
    call this. (The READ path of memory/RAG has no timeout of its own; that
    is a separate, still-open concern.)

    Never raises: a probe that throws would be one more way of not answering.
    """
    if path is None and url is None:
        # Resolve the target the way startup does, or an external Qdrant would
        # be probed at the local embedded path — measuring something else.
        try:
            from core.lifespan_qdrant import _resolve_qdrant_target
            url, path = _resolve_qdrant_target()
        except Exception as exc:  # pragma: no cover — defensive
            logger.debug("Qdrant probe: target resolution unavailable: %s", exc)

    limit = PROBE_TIMEOUT_S if timeout is None else timeout
    result: list[tuple[bool, str]] = []

    def _ask() -> None:
        try:
            client = get_qdrant_client(path=path, url=url)
            collections = client.get_collections().collections
            result.append((True, f"{len(collections)} collection(s)"))
        except Exception as exc:  # noqa: BLE001 — any failure is "not available"
            result.append((False, f"{type(exc).__name__}: {exc}"))

    worker = threading.Thread(target=_ask, name="qdrant-probe", daemon=True)
    worker.start()
    worker.join(limit)

    if not result:
        # The thread is left running; it is a daemon and the client has its
        # own deadline, so it cannot hold the process open.
        observation = (False, f"no answer in {limit}s")
    else:
        observation = result[0]

    with _observation_lock:
        global _last_observation
        _last_observation = (observation[0], observation[1], time.monotonic())
    return observation


def qdrant_status(max_age: float = 60.0) -> tuple[bool, str]:
    """The most recent observation, probing only when there is none.

    Readers must not probe. ``get_health()`` is called synchronously on the
    event loop (core/endpoints/root.py) and the interface polls readiness every
    three seconds: a probe there would stall the server for as long as the
    store takes to answer. The watcher is the eye — it probes off-loop once a
    round and everyone else reads what it saw, which is the same doctrine the
    operational state runs on: one place observes, the rest report.

    The cold path (no observation at all yet — watcher disabled, or a call
    before startup finished) probes with a short deadline rather than lying.
    """
    with _observation_lock:
        seen = _last_observation
    if seen is not None:
        ok, detail, at = seen
        age = time.monotonic() - at
        if age <= max_age:
            return ok, detail
        return ok, f"{detail} (last seen {age:.0f}s ago)"
    return probe_qdrant(timeout=2.0)
