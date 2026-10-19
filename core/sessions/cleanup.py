"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/sessions/cleanup.py
Description: Hourly cleanup of inactive chat sessions (off unless NEXE_SESSION_RETENTION_DAYS is set). Lives next to
             SessionManager so core/lifespan does not import the UI plugin.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import asyncio
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

#: Days of inactivity after which a conversation is deleted. Unset, 0 or
#: anything that is not a positive whole number = NEVER. An assistant with
#: persistent memory that forgot every conversation after 24 h wiped 837 of
#: them on 13/10/2026, one hour after the server was started.
RETENTION_ENV = "NEXE_SESSION_RETENTION_DAYS"


def retention_hours() -> Optional[int]:
    """Hours of inactivity that make a session deletable, or None for never."""
    raw = os.environ.get(RETENTION_ENV, "").strip()
    if not raw:
        return None
    try:
        days = int(raw)
    except ValueError:
        logger.warning("%s=%r is not a whole number of days: sessions are kept", RETENTION_ENV, raw)
        return None
    return days * 24 if days > 0 else None


async def _session_cleanup_loop(session_mgr):
    """Background loop that removes inactive sessions every hour, if asked to.

    The retention is read on every round, so changing it needs no restart.
    """
    while True:
        await asyncio.sleep(3600)
        hours = retention_hours()
        if hours is None:
            continue
        try:
            removed = session_mgr.cleanup_inactive(max_age_hours=hours)
            if removed:
                logger.info("Session cleanup: %d sessions removed", removed)
        except Exception as e:
            logger.warning("Session cleanup failed: %s", e)


def start_session_cleanup_task(session_mgr):
    """Start session cleanup background task. Call from lifespan startup.

    Returns the asyncio.Task so the caller can cancel it on shutdown (N04).
    """
    return asyncio.create_task(_session_cleanup_loop(session_mgr))
