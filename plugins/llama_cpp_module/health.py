"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: plugins/llama_cpp_module/health.py
Description: Facade get_health() for the llama_cpp module.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from typing import Dict, Any

from plugins._shared.health_facade import get_health_facade


def get_health() -> Dict[str, Any]:
    """Synchronous facade to get health of the llama_cpp module."""
    from .manifest import get_module_instance  # type: ignore[attr-defined]  # FP: install_lazy_manifest() injects get_module_instance() dynamically into the module namespace
    return get_health_facade(get_module_instance)
