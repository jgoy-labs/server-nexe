"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: core/loader/__init__.py
Description: No description available.

www.jgoy.net
────────────────────────────────────
"""

from .protocol import (
  NexeModule,
  NexeModuleWithRouter,
  NexeModuleWithSpecialists,
  ModuleMetadata,
  ModuleStatus,
  HealthStatus,
  HealthResult,
  SpecialistInfo,
  validate_module,
  module_has_router,
  module_has_specialists,
)

from .scanner import (
  ModuleScanner,
  ModuleDiscovery,
  scan_modules,
  discover_module,
)

from .registry import (
  ModuleRegistry,
  RegisteredModule,
  get_registry,
)

from .loader import (
  ModuleLoader,
  ModuleLoadError,
  get_loader,
  bootstrap,
)

__all__ = [
  "NexeModule",
  "NexeModuleWithRouter",
  "NexeModuleWithSpecialists",
  "ModuleMetadata",
  "ModuleStatus",
  "HealthStatus",
  "HealthResult",
  "SpecialistInfo",
  "validate_module",
  "module_has_router",
  "module_has_specialists",
  "ModuleScanner",
  "ModuleDiscovery",
  "scan_modules",
  "discover_module",
  "ModuleRegistry",
  "RegisteredModule",
  "get_registry",
  "ModuleLoader",
  "ModuleLoadError",
  "get_loader",
  "bootstrap",
]

__version__ = "1.0.0"