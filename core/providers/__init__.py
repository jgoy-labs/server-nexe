"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/providers/__init__.py
Description: External API providers: declarative registry, key-presence
    status, a connection test and (phase 2) the cloud gate a turn passes before
    it may leave this machine. Nothing here joins the engine cascade.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from .connection import check_connection
from .registry import PROVIDERS, Provider, get_provider, is_configured, provider_status

__all__ = [
    "PROVIDERS",
    "Provider",
    "check_connection",
    "get_provider",
    "is_configured",
    "provider_status",
]
