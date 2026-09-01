"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/lifespan_sessions.py
Description: SessionManager startup + hourly cleanup. Owns the instance so
             /v1 can persist threads without the UI plugin.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import logging

logger = logging.getLogger(__name__)


async def _startup_session_manager(server_state) -> None:
    """Create the process-wide SessionManager after encryption, before plugins."""
    from core.sessions import attach_session_manager
    attach_session_manager(server_state)


async def _startup_session_cleanup(app, server_state) -> None:
    """Start the session cleanup background task (N-5 / N04)."""
    try:
        from core.sessions import start_session_cleanup_task
        session_mgr = getattr(server_state, "session_manager", None)
        if session_mgr is not None:
            server_state._session_cleanup_task = start_session_cleanup_task(session_mgr)
            logger.info("Session cleanup task started (runs every hour)")
        else:
            logger.warning("SessionManager not attached — session cleanup task skipped")
    except Exception as e:
        logger.warning("Could not start session cleanup task: %s", e)
