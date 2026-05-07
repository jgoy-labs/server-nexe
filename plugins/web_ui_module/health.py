"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: plugins/web_ui_module/health.py
Description: get_health() facade for the web_ui module.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import asyncio
from typing import Dict, Any


def get_health() -> Dict[str, Any]:
    """Synchronous facade to get the web_ui module health."""
    from .manifest import get_module_instance  # type: ignore[attr-defined]  # FP: install_lazy_manifest() injecta get_module_instance() dinàmicament al namespace del mòdul

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
