"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy
Location: core/messages.py
Description: Missatges i18n per al core del servidor.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import logging

logger = logging.getLogger(__name__)

FALLBACK_MESSAGES = {
    "core.bootstrap.invalid_ip": "Invalid IP address",
}


def get_message(i18n, key: str, **kwargs) -> str:
    """
    Obté missatge traduït amb fallback.

    Patró idèntic a plugins/security/core/messages.py.
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
