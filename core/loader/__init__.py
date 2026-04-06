"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/loader/__init__.py
Description: Public API of core.loader. Exports the live module protocol
             and the lazy-manifest factory used by every plugin.

www.jgoy.net · https://server-nexe.org
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

from .manifest_base import (
  create_lazy_manifest,
  install_lazy_manifest,
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
  "create_lazy_manifest",
  "install_lazy_manifest",
]

__version__ = "1.0.0"
