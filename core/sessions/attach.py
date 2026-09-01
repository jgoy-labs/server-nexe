"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/sessions/attach.py
Description: Bind the process-wide SessionManager onto ServerState.

Called from core lifespan after encryption and before plugins load, so
/v1 can persist conversation threads without the UI plugin.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)


def attach_session_manager(server_state: Any, *, storage_path: Optional[str] = None) -> Any:
    """Return the process-wide SessionManager, creating it once on server_state.

    Production without a crypto_provider raises: sessions must not land on
    disk as plaintext .json (incident 2026-05-13). Development/test log a
    warning and keep the plaintext fallback.
    """
    existing = getattr(server_state, "session_manager", None)
    if existing is not None:
        return existing

    crypto = getattr(server_state, "crypto_provider", None)
    env = os.environ.get("NEXE_ENV", "production").lower()
    if crypto is None and env == "production":
        raise RuntimeError(
            "SessionManager: crypto_provider is None in production "
            "mode. Encryption-at-rest must be initialized by lifespan_crypto "
            "before SessionManager is constructed. Aborting to prevent plaintext "
            "session storage."
        )
    if crypto is None:
        logger.warning(
            "SessionManager: crypto_provider is None in %s mode — "
            "sessions will be stored as plaintext .json on disk. "
            "Set NEXE_ENV=production or ensure lifespan_crypto runs first.",
            env,
        )

    if storage_path is None:
        from core.paths.helpers import get_data_dir
        storage_path = str(get_data_dir("sessions"))

    from core.sessions.session_manager import SessionManager
    mgr = SessionManager(storage_path=storage_path, crypto_provider=crypto)
    server_state.session_manager = mgr
    logger.info(
        "SessionManager attached (storage=%s, crypto=%s)",
        storage_path,
        "yes" if crypto else "no",
    )
    return mgr
