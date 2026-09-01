"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/sessions/__init__.py
Description: Conversation threads. The UI plugin consumes this; it does not own it.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from .attach import attach_session_manager
from .cleanup import start_session_cleanup_task
from .session_manager import ChatSession, SessionManager

__all__ = [
    "ChatSession",
    "SessionManager",
    "attach_session_manager",
    "start_session_cleanup_task",
]
