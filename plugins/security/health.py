"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: plugins/security/health.py
Description: get_health() facade for the security module.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import asyncio
from typing import Dict, Any


def get_health() -> Dict[str, Any]:
    """
    Synchronous facade to get the security module health.

    Returns dict with status, message, details, checks.
    Delegates to SecurityModule.health_check() (async).
    """
    from .manifest import get_module_instance  # type: ignore[attr-defined]  # FP: install_lazy_manifest() dynamically injects get_module_instance() into the module namespace

    module = get_module_instance()

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # Already inside event loop (e.g. FastAPI) — cannot call asyncio.run()
        # Return a basic synchronous result
        return {
            "status": "healthy" if module._initialized else "unknown",
            "module": module.metadata.name,
            "version": module.metadata.version,
            "initialized": module._initialized,
        }

    # Outside event loop — can run the async health_check
    result = asyncio.run(module.health_check())
    return result.to_dict()
