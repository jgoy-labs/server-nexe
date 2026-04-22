"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/loader/__init__.py
Description: API pública de core.loader. Exporta el protocol de mòdul
             i la factoria de manifest lazy que fa servir tot plugin.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from core.version import __version__

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
  "__version__",
]
