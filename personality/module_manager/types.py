"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: personality/module_manager/types.py
Description: Shared dataclasses for module_manager sub-components.
Groups related parameters to reduce function arity.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RouterContext:
    """Groups parameters for router attachment operations."""

    app: Any
    manifest_module: Any
    module_name: str
    removed_routes: list = field(default_factory=list)


@dataclass
class SecurityCheckContext:
    """Groups parameters for plugin security allowlist checks."""

    app: Any
    module_name: str
    module_info: Any
    allowlist_config: dict


@dataclass
class LifecycleConfig:
    """Dependencies for ModuleLifecycleManager."""

    modules: dict
    loader: Any
    registry: Any
    events: Any
    metrics: Any
    i18n: Any = None


@dataclass
class SystemLifecycleConfig:
    """Dependencies for SystemLifecycleManager."""

    modules: dict
    module_lifecycle: Any
    discovery_func: Any
    list_modules_func: Any
    i18n: Any = None


@dataclass
class DiscoveryConfig:
    """Dependencies for ModuleDiscovery."""

    path_discovery: Any
    config_manager: Any
    events: Any
    i18n: Any = None
