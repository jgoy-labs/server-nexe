"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: personality/integration/types.py
Description: Shared dataclasses for integration sub-components.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from dataclasses import dataclass
from typing import Any


@dataclass
class RouteRegistration:
    """Groups parameters for route registration operations."""

    module_name: str
    api_component: Any
    prefix: str
    component_type: str
