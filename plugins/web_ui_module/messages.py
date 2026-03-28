"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy
Location: plugins/web_ui_module/messages.py
Description: Missatges i18n per al modul web_ui.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import logging

logger = logging.getLogger(__name__)

FALLBACK_MESSAGES = {
    "webui.auth.invalid_key": "Invalid or missing API key",
    "webui.static.ui_not_found": "UI not found",
    "webui.static.forbidden": "Forbidden",
    "webui.static.file_not_found": "File not found",
    "webui.session.not_found": "Session not found",
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
