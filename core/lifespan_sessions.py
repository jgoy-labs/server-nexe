"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/lifespan_sessions.py
Description: Session cleanup task startup helper extracted from lifespan.py.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import logging

logger = logging.getLogger(__name__)


async def _startup_session_cleanup(app, server_state) -> None:
    """Start the session cleanup background task (N-5 / N04)."""
    try:
        from plugins.web_ui_module.api.routes import start_session_cleanup_task
        web_ui = app.state.modules.get("web_ui_module")
        if web_ui and hasattr(web_ui, 'session_manager'):
            server_state._session_cleanup_task = start_session_cleanup_task(web_ui.session_manager)
            logger.info("Session cleanup task started (runs every hour)")
        else:
            logger.warning("web_ui_module not loaded — session cleanup task skipped")
    except Exception as e:
        logger.warning("Could not start session cleanup task: %s", e)
