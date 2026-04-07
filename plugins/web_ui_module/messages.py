"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: plugins/web_ui_module/messages.py
Description: Missatges i18n per al modul web_ui.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import logging
from fastapi import Request

logger = logging.getLogger(__name__)

FALLBACK_MESSAGES = {
    "webui.auth.invalid_key": "Invalid or missing API key",
    "webui.auth.no_key_configured": "Server has no admin API key configured (FAIL CLOSED). Set NEXE_PRIMARY_API_KEY or NEXE_ADMIN_API_KEY.",
    "webui.auth.supported_languages": "Supported languages: ca, es, en",
    "webui.static.ui_not_found": "UI not found",
    "webui.static.forbidden": "Forbidden",
    "webui.static.file_not_found": "File not found",
    "webui.session.not_found": "Session not found",
    "webui.session.name_length": "Name must be 1-100 chars",
    "webui.file.extract_failed": "Could not extract text from file",
    "webui.chat.message_required": "Message is required",
    "webui.memory.content_required": "Content is required",
    "webui.memory.query_required": "Query is required",
}


def get_message(i18n, key: str, **kwargs) -> str:
    """
    Get translated message with fallback.

    Same pattern as plugins/security/core/messages.py.
    """
    if i18n:
        try:
            result = i18n.t(key, **kwargs)
            if result and result != key:
                return result
        except Exception as e:
            logger.debug("i18n translation failed for %s: %s", key, e)
    template = FALLBACK_MESSAGES.get(key, key)
    try:
        return template.format(**kwargs)
    except (KeyError, IndexError):
        return template


def get_i18n(request: Request):
    """FastAPI Dependency: read i18n from app.state.

    Returns None if app.state has no i18n attribute (test/dev fallback).
    Same pattern as core/endpoints/root.py::get_i18n.

    Used by Web UI routes to inject i18n into get_message() calls
    instead of passing None (Codex P1 i18n bypass fix — Q3).

    Note: the `request: Request` type hint is REQUIRED for FastAPI to
    inject the Request object. Without it, FastAPI treats `request` as
    a query parameter and returns 422 Unprocessable Entity.
    """
    return getattr(request.app.state, "i18n", None)
