"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: plugins/_shared/health_facade.py
Description: Shared synchronous get_health() facade for plugin modules (MC-095).
             Each module's health.py delegates here, passing its own call-time
             get_module_instance so test patching keeps working.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import asyncio
from typing import Any, Callable, Dict


def get_health_facade(get_module_instance: Callable[[], Any]) -> Dict[str, Any]:
    """Synchronous facade returning the health of a plugin module.

    Args:
        get_module_instance: Callable returning the module singleton. The caller
            imports it at call time (from .manifest) so test patches apply.
    """
    module = get_module_instance()

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        return {
            "status": "healthy" if module._initialized else "unknown",
            "module": module.metadata.name,
            "version": module.metadata.version,
            "initialized": module._initialized,
        }

    result = asyncio.run(module.health_check())
    return result.to_dict()
