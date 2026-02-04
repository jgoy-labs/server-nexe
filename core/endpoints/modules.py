"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: core/endpoints/modules.py
Description: Endpoints FastAPI per module integration. Routes: /modules (list), /modules/{name}/routes.

www.jgoy.net
────────────────────────────────────
"""

from fastapi import APIRouter, Request, Depends

from core.dependencies import limiter

from core.models import (
  ModulesListResponse,
  ModuleRoutesResponse
)

router = APIRouter()

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

@router.get("/modules", response_model=ModulesListResponse)
@limiter.limit("10/minute")
async def list_integrated_modules(
  request: Request,
  i18n=Depends(get_i18n),
  api_integrator=Depends(get_api_integrator)
) -> ModulesListResponse:
  """List integrated modules and their APIs"""
  if api_integrator:
    stats = api_integrator.get_integration_stats()
    return ModulesListResponse(
      status=i18n.t('server_core.api.responses.success') if i18n else "correcte",
      data=stats
    )
  else:
    return ModulesListResponse(
      status=i18n.t('server_core.api.responses.error') if i18n else "error",
      message=i18n.t('server_core.api.errors.integrator_not_initialized') if i18n else
          "Integrador d'API no inicialitzat"
    )

@router.get("/modules/{module_name}/routes", response_model=ModuleRoutesResponse)
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
      status=i18n.t('server_core.api.responses.success') if i18n else "correcte",
      module=module_name,
      routes=routes
    )
  else:
    return ModuleRoutesResponse(
      status=i18n.t('server_core.api.responses.error') if i18n else "error",
      message=i18n.t('server_core.api.errors.integrator_not_initialized') if i18n else
          "Integrador d'API no inicialitzat"
    )