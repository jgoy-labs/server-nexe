"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/server/factory_modules.py
Description: Module Discovery and Loading for Nexe Server Factory.

Uses ModuleManager as SINGLE SOURCE OF TRUTH for all module operations.
See: docs/NEXE_ARCHITECTURAL_DECISIONS.md (ADR-001)

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import logging
from pathlib import Path
from typing import Any, List

from .helpers import translate

logger = logging.getLogger(__name__)

def discover_and_load_modules(app: Any, module_manager: Any, project_root: Path, i18n: Any) -> List[str]:
  """
  Auto-discover modules and load their routers.

  Uses ModuleManager.load_plugin_routers() - the SINGLE SOURCE OF TRUTH.

  Args:
    app: FastAPI application
    module_manager: ModuleManager instance
    project_root: Project root path
    i18n: I18n manager

  Returns:
    List of discovered module names
  """
  logger.info(translate(i18n, "core.server.auto_discovering",
             "Auto-discovering modules from: {path}",
             path=str(project_root / 'plugins')))

  discovered = module_manager.discover_modules_sync(force=False)

  logger.info(translate(i18n, "core.server.modules_discovered",
             "Discovered {count} modules: {modules}",
             count=len(discovered),
             modules=', '.join(discovered)))

  try:
    from personality.integration.api_integrator import APIIntegrator
    api_integrator = APIIntegrator(app, i18n)
    module_manager.set_api_integrator(api_integrator)
    logger.debug(translate(i18n, "core.server.api_integrator_configured",
                "🔌 API integrator configured"))
  except ImportError:
    logger.warning(translate(i18n, "core.server.api_integrator_unavailable",
                 "API integrator not available (integration module missing)"))

  # Use ModuleManager directly (SINGLE SOURCE OF TRUTH)
  module_manager.load_plugin_routers(app, project_root, discovered)

  return discovered

__all__ = ['discover_and_load_modules']