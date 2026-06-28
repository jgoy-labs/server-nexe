"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: plugins/mlx_module/health.py
Description: get_health() facade for the mlx module.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from typing import Dict, Any

from plugins._shared.health_facade import get_health_facade


def get_health() -> Dict[str, Any]:
    """Synchronous facade to get the health of the mlx module."""
    from .manifest import get_module_instance  # type: ignore[attr-defined]  # FP: install_lazy_manifest() injects get_module_instance() dynamically into the module namespace
    return get_health_facade(get_module_instance)
