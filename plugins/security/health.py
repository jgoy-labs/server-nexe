"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: plugins/security/health.py
Description: get_health() facade for the security module.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from typing import Dict, Any

from plugins._shared.health_facade import get_health_facade


def get_health() -> Dict[str, Any]:
    """
    Synchronous facade to get the security module health.

    Returns dict with status, message, details, checks.
    Delegates to SecurityModule.health_check() (async).
    """
    from .manifest import get_module_instance  # type: ignore[attr-defined]  # FP: install_lazy_manifest() dynamically injects get_module_instance() into the module namespace
    return get_health_facade(get_module_instance)
