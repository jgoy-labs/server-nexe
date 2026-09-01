"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/sessions/cleanup.py
Description: Hourly cleanup of inactive chat sessions. Lives next to
             SessionManager so core/lifespan does not import the UI plugin.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import asyncio
import logging

logger = logging.getLogger(__name__)


async def _session_cleanup_loop(session_mgr):
    """Background loop that removes inactive sessions every hour."""
    while True:
        await asyncio.sleep(3600)
        try:
            removed = session_mgr.cleanup_inactive(max_age_hours=24)
            if removed:
                logger.info("Session cleanup: %d sessions removed", removed)
        except Exception as e:
            logger.warning("Session cleanup failed: %s", e)


def start_session_cleanup_task(session_mgr):
    """Start session cleanup background task. Call from lifespan startup.

    Returns the asyncio.Task so the caller can cancel it on shutdown (N04).
    """
    return asyncio.create_task(_session_cleanup_loop(session_mgr))
