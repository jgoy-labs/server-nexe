"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: plugins/llama_cpp_module/health.py
Description: Facade get_health() for the llama_cpp module.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import asyncio
from typing import Dict, Any


def get_health() -> Dict[str, Any]:
    """Synchronous facade to get health of the llama_cpp module."""
    from .manifest import get_module_instance  # type: ignore[attr-defined]  # FP: install_lazy_manifest() injects get_module_instance() dynamically into the module namespace

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
