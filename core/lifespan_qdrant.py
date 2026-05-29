"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/lifespan_qdrant.py
Description: Qdrant singleton pool startup/shutdown helpers extracted from lifespan.py.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import logging
import os
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# Bug #5 (2026-05-21): backoff schedule for Qdrant lock acquisition on
# restart. POSIX flock release can lag process exit by tens-of-ms; without a
# retry the second sidecar fails with "Storage folder already accessed". Five
# attempts (0, 100, 200, 400, 800 ms = 1.5 s total) cover the empirical
# window observed in nexe-app live tests without unduly delaying healthy
# starts. Tuned to be cheap when the lock is free (first try succeeds).
_LOCK_RETRY_BACKOFF_S = (0.0, 0.1, 0.2, 0.4, 0.8)


def _resolve_qdrant_target() -> tuple[Optional[str], Optional[str]]:
    """Return (url, path) the same way _startup_qdrant has historically done.

    The url takes precedence; when set, path is None (remote mode).
    Falls back to NEXE_QDRANT_PATH env / "storage/vectors" if SidecarConfig
    is unavailable.
    """
    qdrant_url = os.environ.get("NEXE_QDRANT_URL")
    qdrant_path: Optional[str]
    try:
        from core.sidecar_config import get_sidecar_config
        sidecar_cfg = get_sidecar_config()
        if sidecar_cfg.qdrant_url:
            qdrant_url = sidecar_cfg.qdrant_url
        qdrant_path = str(sidecar_cfg.vectors_dir)
    except Exception:  # pragma: no cover — fallback to pre-sidecar behaviour
        qdrant_path = os.environ.get("NEXE_QDRANT_PATH", "storage/vectors")
    if qdrant_url:
        return qdrant_url, None
    return None, qdrant_path


def _startup_qdrant() -> None:
    """Initialize the Qdrant singleton pool with lock-retry backoff.

    In sidecar mode, paths come from SidecarConfig
    (NEXE_QDRANT_PATH respected explicitly) — resolves anomaly A5
    "NEXE_QDRANT_PATH not respected".

    Bug #5 (2026-05-21): retry with backoff if the previous sidecar
    has not fully released `vectors/.lock` yet. Without this, a clean restart
    cycle (sidecar 1 exits → sidecar 2 starts within ~1 s) requires the
    skill consumer to do `sleep 5 + rm -f vectors/.lock` manually. The
    retry covers the empirical window observed in nexe-app live tests T6.
    """
    from core.qdrant_pool import get_qdrant_client

    qdrant_url, qdrant_path = _resolve_qdrant_target()

    last_error: Optional[Exception] = None
    for attempt, delay in enumerate(_LOCK_RETRY_BACKOFF_S):
        if delay > 0:
            time.sleep(delay)
        try:
            get_qdrant_client(url=qdrant_url, path=qdrant_path)
            if attempt > 0:
                logger.info(
                    "Qdrant lock acquired on retry %d (target=%s)",
                    attempt,
                    qdrant_url or qdrant_path,
                )
            return
        except RuntimeError as e:
            if "already accessed" not in str(e):
                raise  # unrelated RuntimeError, do not swallow
            last_error = e
            logger.warning(
                "Qdrant storage still locked (attempt %d/%d); will retry",
                attempt + 1,
                len(_LOCK_RETRY_BACKOFF_S),
            )

    assert last_error is not None  # nosec B101 — invariant: loop ran at least once; assert is correct here
    raise last_error


def _shutdown_qdrant() -> None:
    """Close the Qdrant singleton pool and emit a diagnostic warning if the
    `.lock` sentinel is still held afterwards.

    Bug #5 (2026-05-21): the diagnostic is best-effort and never
    blocks shutdown. We do NOT delete the `.lock` file — it is a sentinel,
    not the actual lock (POSIX flock lives in the FD), and deleting it
    would mask real two-instance contention. The next sidecar startup
    will retry-with-backoff via `_startup_qdrant`.
    """
    try:
        from core.qdrant_pool import close_qdrant_client
        close_qdrant_client()
        logger.info("Qdrant pool closed")
    except Exception as e:
        logger.debug("Qdrant pool close failed: %s", e)
        return
    _warn_if_lock_still_held()


def _warn_if_lock_still_held() -> None:
    """Best-effort: log a warning if the `.lock` file appears to still be held
    after `close_qdrant_client()`. Never raises, never blocks shutdown."""
    try:
        _, qdrant_path = _resolve_qdrant_target()
        if not qdrant_path:
            return  # remote mode — no local lock file
        lock_file = Path(qdrant_path) / ".lock"
        if not lock_file.exists():
            return  # nothing to check

        import portalocker  # transitive dep of qdrant-client; always present

        with open(lock_file, "r+") as fd:
            try:
                portalocker.lock(
                    fd,
                    portalocker.LockFlags.EXCLUSIVE
                    | portalocker.LockFlags.NON_BLOCKING,
                )
                portalocker.unlock(fd)
                # Lock was free — close() released it cleanly.
            except portalocker.exceptions.LockException:
                logger.warning(
                    "Qdrant .lock still held after close (%s); "
                    "next startup will retry-with-backoff",
                    lock_file,
                )
    except Exception as e:
        # Never let a diagnostic failure propagate during shutdown.
        logger.debug("Qdrant lock diagnostic failed: %s", e)
