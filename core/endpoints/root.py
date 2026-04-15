"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/endpoints/root.py
Description: Basic FastAPI server endpoints. Routes: / (system info), /health (health check),

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import os
from datetime import datetime, timezone
from fastapi import APIRouter, Request, Depends

from core.version import __version__

from core.dependencies import limiter, get_i18n
from plugins.security.core.auth_dependencies import require_api_key

from core.resilience import (
  ollama_breaker,
  qdrant_breaker,
  http_breaker,
)

from core.models import (
  SystemResponse,
  HealthResponse,
  ApiInfoResponse,
  EndpointInfo
)

router = APIRouter(tags=["system"])

def _get_qdrant_status() -> bool:
  """Fallback: check qdrant status from server_state."""
  try:
    from core.lifespan import server_state
    return getattr(server_state, 'qdrant_available', False)
  except Exception:
    return False

def _normalize_engine(engine: str) -> str:
  if not engine:
    return ""
  value = engine.strip().lower()
  if value in {"llama.cpp", "llama-cpp", "llamacpp"}:
    return "llama_cpp"
  return value

def _required_modules_from_config(config: dict) -> set:
  # Inference engines are OPTIONAL at readiness time. A user can have all
  # three approved (so the Motor dropdown shows them) but only have a model
  # configured for one. Marking a modelless engine as required made the
  # whole UI bail with status=unhealthy — unusable first-run UX. Only the
  # actively-selected engine (preferred_engine) stays required.
  OPTIONAL_ENGINES = {"mlx_module", "llama_cpp_module", "ollama_module"}

  required = set()
  modules_cfg = config.get("plugins", {}).get("modules", {})
  enabled = set(modules_cfg.get("enabled", []))
  # Cross with NEXE_APPROVED_MODULES env var — installer may restrict the allowlist
  import os
  approved_env = os.environ.get("NEXE_APPROVED_MODULES", "")
  if approved_env:
    approved = {m.strip() for m in approved_env.split(",") if m.strip()}
    enabled = enabled & approved  # only require modules that are both enabled AND approved
  # Drop optional engines from the core requirement set; the preferred one is
  # re-added below if explicitly selected.
  required.update(enabled - OPTIONAL_ENGINES)

  preferred_engine = _normalize_engine(
    config.get("plugins", {}).get("models", {}).get("preferred_engine", "")
  )
  engine_map = {
    "ollama": "ollama_module",
    "mlx": "mlx_module",
    "llama_cpp": "llama_cpp_module",
  }
  # Only require the preferred engine if it's both configured and enabled.
  # "auto" or empty → no engine required (user can pick at runtime).
  if preferred_engine in engine_map and engine_map[preferred_engine] in enabled:
    required.add(engine_map[preferred_engine])

  return required

async def _module_health_status(instance) -> str:
  if hasattr(instance, "get_health"):
    try:
      health = instance.get_health()
      return health.get("status", "unhealthy")
    except Exception:
      return "unhealthy"
  if hasattr(instance, "health_check"):
    try:
      result = await instance.health_check()
      return getattr(result, "status", "unknown").value
    except Exception:
      return "unhealthy"
  return "unknown"

@router.get("/", response_model=SystemResponse, summary="General system information")
@limiter.limit("30/minute")
async def root(request: Request, i18n=Depends(get_i18n)) -> SystemResponse:
  """Root endpoint with system information"""
  return SystemResponse(
    system=f"Nexe {__version__}",
    description=i18n.t('server_core.api.welcome.description') if i18n else
          "Module orchestration system running",
    status=i18n.t('server_core.api.welcome.ready') if i18n else
        "System ready and operational",
    version=__version__,
    type=i18n.t('server_core.api.server_type') if i18n else "basic_server"
  )

@router.get("/health", response_model=HealthResponse, summary="Basic server health check")
@limiter.limit("60/minute")
async def health_check(request: Request, i18n=Depends(get_i18n)) -> HealthResponse:
  """System health check"""
  return HealthResponse(
    status=i18n.t('server_core.api.health.status') if i18n else "operational",
    message=i18n.t('server_core.api.health.message') if i18n else
        "Basic server operational",
    version=__version__,
    uptime=i18n.t('server_core.api.health.uptime') if i18n else "operational"
  )

@router.get("/health/ready", summary="Readiness check — verifies required modules")
@limiter.limit("120/minute")
async def readiness_check(request: Request) -> dict:
  """
  Readiness check.

  Verifies that the required modules are loaded and healthy.
  """
  config = getattr(request.app.state, "config", {}) or {}
  modules = getattr(request.app.state, "modules", {}) or {}

  required = _required_modules_from_config(config)

  missing = []
  unhealthy = []
  degraded = []
  statuses = {}

  for module_name in sorted(required):
    instance = modules.get(module_name)
    if not instance:
      missing.append(module_name)
      continue

    status = await _module_health_status(instance)
    statuses[module_name] = status
    if status == "unhealthy":
      unhealthy.append(module_name)
    elif status == "degraded":
      degraded.append(module_name)
    elif status == "unknown":
      degraded.append(module_name)

  if missing or unhealthy:
    overall = "unhealthy"
  elif degraded:
    overall = "degraded"
  else:
    overall = "healthy"

  # SECURITY: Return minimal status without exposing internal module details.
  return {
    "status": overall,
    "timestamp": datetime.now(timezone.utc).isoformat(),
  }

@router.get("/api/info", response_model=ApiInfoResponse, summary="API information and list of available endpoints")
@limiter.limit("30/minute")
async def system_info(request: Request, i18n=Depends(get_i18n)) -> ApiInfoResponse:
  """Basic system information"""

  endpoints = [
    EndpointInfo(
      path="/",
      method="GET",
      description=i18n.t('server_core.api.endpoints.root_description') if i18n else
            "System root endpoint"
    ),
    EndpointInfo(
      path="/health",
      method="GET",
      description=i18n.t('server_core.api.endpoints.health_description') if i18n else
            "System health check"
    ),
    EndpointInfo(
      path="/api/info",
      method="GET",
      description=i18n.t('server_core.api.endpoints.info_description') if i18n else
            "Basic system information"
    )
  ]

  return ApiInfoResponse(
    name=f"Nexe {__version__}",
    version=__version__,
    description=i18n.t('server_core.api.welcome.description') if i18n else
          "Module orchestration system running",
    endpoints=endpoints
  )


def _check_llama_cpp_available(modules: dict) -> bool:
  """Check if llama_cpp_module is loaded AND has a working _node.

  Symmetric with the MLX check inside /status (P0-2.c): only reports True
  when the module has an active backend, not just when the dict key exists.
  This catches edge cases where the loader didn't pop a failed module
  (e.g., exception path from P0-2.b design choice).

  Extracted as a pure helper so it can be unit-tested without a real
  starlette.Request (slowapi's @limiter.limit rejects MagicMock).
  """
  if "llama_cpp_module" not in modules:
    return False
  instance = modules["llama_cpp_module"]
  return hasattr(instance, '_node') and instance._node is not None


@router.get("/status", summary="Real-time status: active engine, model, and loaded modules (API key required)")
@limiter.limit("60/minute")
async def server_status(
  request: Request,
  _: str = Depends(require_api_key),
) -> dict:
  """
  Server status endpoint with actual runtime configuration.

  Returns:
  - engine: The actual LLM engine being used (may differ from .env if fallback occurred)
  - model: Current model loaded
  - modules: Loaded modules status
  """
  # Load .env to get configured engine
  env_engine = os.getenv("NEXE_MODEL_ENGINE", "auto")
  env_model = os.getenv("NEXE_DEFAULT_MODEL", "unknown")

  # Detect actual engine from loaded modules
  modules = getattr(request.app.state, "modules", {})
  actual_engine = env_engine

  # Check which engine module is actually initialized and working
  mlx_available = False
  llama_cpp_available = False
  ollama_available = False

  if "mlx_module" in modules:
    mlx_instance = modules["mlx_module"]
    # Check if MLX actually has a working node
    if hasattr(mlx_instance, '_node') and mlx_instance._node is not None:
      mlx_available = True

  # P0-2.c: use extracted helper for unit-testability (slowapi blocks direct
  # call with MagicMock request, so the logic lives in a pure function).
  llama_cpp_available = _check_llama_cpp_available(modules)

  if "ollama_module" in modules:
    ollama_available = True

  # Determine actual engine based on what's available
  if env_engine == "mlx" and not mlx_available:
    # MLX configured but not working → fallback to ollama
    actual_engine = "ollama"
  elif env_engine == "llama_cpp" and not llama_cpp_available:
    actual_engine = "ollama"

  return {
    "engine": actual_engine,
    "configured_engine": env_engine,
    "model": env_model,
    "modules_loaded": list(modules.keys()),
    "engines_available": {
      "mlx": mlx_available,
      "llama_cpp": llama_cpp_available,
      "ollama": ollama_available
    },
    "qdrant_available": getattr(request.app.state, "qdrant_available", False) if hasattr(request.app.state, "qdrant_available") else _get_qdrant_status(),
    "timestamp": datetime.now(timezone.utc).isoformat(),
  }

@router.get("/health/circuits", summary="Circuit breaker status (Ollama, Qdrant, external HTTP) (API key required)")
@limiter.limit("30/minute")
async def circuit_status(
  request: Request,
  _: str = Depends(require_api_key),
) -> dict:
  """
  Circuit Breaker status endpoint.

  Returns the current state of all circuit breakers:
  - ollama: LLM inference service
  - qdrant: Vector search service
  - http_external: External HTTP services

  States:
  - closed: Normal operation
  - open: Service failing, requests rejected
  - half_open: Testing if service recovered
  """
  return {
    "circuits": [
      ollama_breaker.get_status(),
      qdrant_breaker.get_status(),
      http_breaker.get_status(),
    ],
    "timestamp": datetime.now(timezone.utc).isoformat(),
  }
