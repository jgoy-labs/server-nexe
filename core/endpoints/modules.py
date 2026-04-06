"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: core/endpoints/modules.py
Description: Endpoints FastAPI per module integration. Routes: /modules (list), /modules/{name}/routes.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from fastapi import APIRouter, Request, Depends

from core.dependencies import limiter
from plugins.security.core.auth_dependencies import require_api_key

from core.models import (
  ModulesListResponse,
  ModuleRoutesResponse
)

router = APIRouter(tags=["modules"])

def get_i18n(request: Request):
  """Get i18n from app state"""
  return getattr(request.app.state, 'i18n', None)

def get_api_integrator(request: Request):
  """Get API integrator from lifespan state"""
  from core.lifespan import get_server_state
  server_state = get_server_state()
  return server_state.api_integrator

def configure_dependencies(api_integrator_instance, i18n_manager):
  """Legacy compatibility - dependencies now injected via app.state"""

@router.get(
  "/modules",
  response_model=ModulesListResponse,
  summary="List integrated modules and their APIs",
  dependencies=[Depends(require_api_key)],
)
@limiter.limit("10/minute")
async def list_integrated_modules(
  request: Request,
  i18n=Depends(get_i18n),
  api_integrator=Depends(get_api_integrator)
) -> ModulesListResponse:
  """List integrated modules and their APIs"""
  if api_integrator:
    stats = api_integrator.get_integration_stats()
    all_modules = getattr(request.app.state, 'modules', {})
    stats['modules_loaded'] = list(all_modules.keys())
    stats['total_modules_loaded'] = len(all_modules)
    return ModulesListResponse(
      status=i18n.t('server_core.api.responses.success') if i18n else "ok",
      data=stats
    )
  else:
    return ModulesListResponse(
      status=i18n.t('server_core.api.responses.error') if i18n else "error",
      message=i18n.t('server_core.api.errors.integrator_not_initialized') if i18n else
          "API integrator not initialized"
    )

@router.get(
  "/modules/{module_name}/routes",
  response_model=ModuleRoutesResponse,
  summary="Registered routes for a specific module",
  dependencies=[Depends(require_api_key)],
)
@limiter.limit("10/minute")
async def get_module_routes(
  module_name: str,
  request: Request,
  i18n=Depends(get_i18n),
  api_integrator=Depends(get_api_integrator)
) -> ModuleRoutesResponse:
  """Get routes for a specific module"""

  if api_integrator:
    routes = api_integrator.get_module_routes(module_name)
    return ModuleRoutesResponse(
      status=i18n.t('server_core.api.responses.success') if i18n else "ok",
      module=module_name,
      routes=routes
    )
  else:
    return ModuleRoutesResponse(
      status=i18n.t('server_core.api.responses.error') if i18n else "error",
      message=i18n.t('server_core.api.errors.integrator_not_initialized') if i18n else
          "API integrator not initialized"
    )