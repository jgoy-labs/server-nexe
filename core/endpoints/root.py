"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/endpoints/root.py
Description: Basic FastAPI server endpoints. Routes: / (system info), /health (health check),

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Request, Depends

from core.version import __version__
from core.i18n_utils import translate
from core.uptime import uptime_str

logger = logging.getLogger(__name__)

from core.dependencies import limiter, get_i18n  # noqa: E402
from plugins.security.core.auth_dependencies import require_api_key  # noqa: E402

from core.resilience import ollama_breaker  # noqa: E402

from core.models import (  # noqa: E402
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
  """Normalize engine name to its canonical snake_case form."""
  if not engine:
    return ""
  value = engine.strip().lower()
  if value in {"llama.cpp", "llama-cpp", "llamacpp"}:
    return "llama_cpp"
  return value

def _required_modules_from_config(config: dict) -> set:
  """Determine which modules are required based on config and environment."""
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
  # Require the preferred engine if explicitly configured.
  # "auto" or empty → no engine required (user can pick at runtime).
  if preferred_engine in engine_map:
    required.add(engine_map[preferred_engine])

  return required

async def _module_health_status(instance) -> str:
  """Return the health status string of a module instance."""
  if hasattr(instance, "get_health"):
    try:
      health = instance.get_health()
      return health.get("status", "unhealthy")
    except Exception:
      return "unhealthy"
  if hasattr(instance, "health_check"):
    try:
      result = await instance.health_check()
      return getattr(result, "status", "unknown").value  # type: ignore[union-attr]  # defensive: str fallback "unknown" triggers AttributeError on .value, caught at line 99 returning literal "unhealthy"
    except Exception:
      return "unhealthy"
  return "unknown"

@router.get("/", response_model=SystemResponse, summary="General system information", operation_id="root")
@limiter.limit("30/minute")
async def root(request: Request, i18n=Depends(get_i18n)) -> SystemResponse:
  """Root endpoint with system information"""
  # usem translate() canònica en comptes de l'inline ternari.
  return SystemResponse(
    system=f"Nexe {__version__}",
    description=translate(i18n, 'server_core.api.welcome.description',
          "Module orchestration system running"),
    status=translate(i18n, 'server_core.api.welcome.ready',
        "System ready and operational"),
    version=__version__,
    type=translate(i18n, 'server_core.api.server_type', "basic_server")
  )

@router.get("/health", response_model=HealthResponse, summary="Basic server health check", operation_id="health_check")
@limiter.limit("60/minute")
async def health_check(request: Request, i18n=Depends(get_i18n)) -> HealthResponse:
  """System health check"""
  # usem translate() canònica en comptes de l'inline ternari.
  return HealthResponse(
    status=translate(i18n, 'server_core.api.health.status', "operational"),
    message=translate(i18n, 'server_core.api.health.message',
        "Basic server operational"),
    version=__version__,
    # B075-C1: report real seconds since startup, not the fixed "operational"
    # label that masqueraded as a metric.
    uptime=uptime_str()
  )

@router.get("/health/ready", summary="Readiness check — verifies required modules", response_model=dict, operation_id="readiness_check")
@limiter.limit("120/minute")
async def readiness_check(request: Request) -> dict:
  """
  Readiness check.

  Verifies that the required modules are loaded and healthy.
  """
  # in minimal_mode (pre-onboarding)
  # the rag/security/web_ui_module modules are NOT started by design. The
  # sidecar IS ready for what it offers (/installer/* endpoints for the
  # wizard). We return "healthy" so the frontend readinessOverlay
  # (public/ui/static/app.js:723) disappears and the wizard can render.
  # Without this fix, the app stays stuck at "Starting..." because the
  # frontend polls /health/ready every 3s and blocks the UI until "healthy".
  if bool(getattr(request.app.state, "minimal_mode", False)):
    return {
      "status": "healthy",
      "minimal_mode": True,
      "timestamp": datetime.now(timezone.utc).isoformat(),
    }

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

  # instrumentation: log which module(s) drove a non-healthy
  # verdict so the next empirical session has the data to fix the root
  # cause. SECURITY: the log line is server-internal — clients still see
  # only the minimal payload below (no per-module details exposed).
  if overall != "healthy":
    logger.warning(
      "readiness=%s missing=%s unhealthy=%s degraded=%s required=%s statuses=%s",
      overall,
      sorted(missing),
      sorted(unhealthy),
      sorted(degraded),
      sorted(required),
      statuses,
    )

  # SECURITY: Return minimal status without exposing internal module details.
  return {
    "status": overall,
    "timestamp": datetime.now(timezone.utc).isoformat(),
  }

@router.get("/api/info", response_model=ApiInfoResponse, summary="API information and a representative subset of public endpoints", operation_id="api_info")
@limiter.limit("30/minute")
async def system_info(request: Request, i18n=Depends(get_i18n)) -> ApiInfoResponse:
  """Basic system information"""

  # B075-C2: this is a deliberately curated, quick-start subset of *public*
  # endpoints — NOT an exhaustive inventory. The full route list is the gated
  # OpenAPI schema; enumerating app.routes here would expose the whole attack
  # surface to unauthenticated callers. The summary/model no longer promise
  # completeness.
  # usem translate() canònica en comptes de l'inline ternari.
  endpoints = [
    EndpointInfo(
      path="/",
      method="GET",
      description=translate(i18n, 'server_core.api.endpoints.root_description',
            "System root endpoint")
    ),
    EndpointInfo(
      path="/health",
      method="GET",
      description=translate(i18n, 'server_core.api.endpoints.health_description',
            "System health check")
    ),
    EndpointInfo(
      path="/api/info",
      method="GET",
      description=translate(i18n, 'server_core.api.endpoints.info_description',
            "Basic system information")
    )
  ]

  return ApiInfoResponse(
    name=f"Nexe {__version__}",
    version=__version__,
    description=translate(i18n, 'server_core.api.welcome.description',
          "Module orchestration system running"),
    endpoints=endpoints
  )


# B260: the legacy node-aware helpers (_check_llama_cpp_available and
# _resolve_effective_engine) are GONE. Engine availability and resolution now
# live in a SINGLE source of truth — routing._engine_available /
# routing._resolve_engine — which /status delegates to (see server_status). This
# removes the parallel reimplementation that B075-C6 had to keep in lockstep.

@router.get("/status", summary="Real-time status: active engine, model, and loaded modules (API key required)", response_model=dict, operation_id="server_status")
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
  # runtime override (live UI selection) > env (.env install-time).
  from core.runtime_state import get_with_env_fallback
  env_engine = get_with_env_fallback("NEXE_MODEL_ENGINE", "auto")
  env_model = get_with_env_fallback("NEXE_DEFAULT_MODEL", "unknown")

  # Detect actual engine from loaded modules
  modules = getattr(request.app.state, "modules", {})
  actual_engine = env_engine

  # B260: availability is node-aware and sourced from the SINGLE canonical
  # definition the chat router uses (routing._engine_available), so /status can
  # never drift from what a real chat call resolves.
  from core.endpoints.chat_engines.routing import _engine_available, _resolve_engine
  mlx_available = _engine_available("mlx", request.app.state)
  llama_cpp_available = _engine_available("llama_cpp", request.app.state)
  ollama_available = _engine_available("ollama", request.app.state)

  # Determine actual engine based on what's available
  if env_engine == "mlx" and not mlx_available:
    # MLX configured but not working → fallback to ollama
    actual_engine = "ollama"
  elif env_engine == "llama_cpp" and not llama_cpp_available:
    actual_engine = "ollama"

  # B260/B075-C6: resolved_engine DELEGATES to the canonical chat resolver, so it
  # reports exactly what a chat call with no explicit engine would run — zero
  # drift, single source of truth. The legacy `engine`/`configured_engine`
  # fields stay untouched for backward-compat (web UI + documented API).
  resolved_engine, _ = _resolve_engine(None, request.app.state)

  # Expose minimal_mode flag so the frontend knows whether the sidecar
  # is in reduced pre-onboarding mode. We don't change the existing format
  # (the web UI depends on the current fields); we add an optional field.
  return {
    "engine": actual_engine,
    "configured_engine": env_engine,
    "resolved_engine": resolved_engine,
    "model": env_model,
    "modules_loaded": list(modules.keys()),
    "engines_available": {
      "mlx": mlx_available,
      "llama_cpp": llama_cpp_available,
      "ollama": ollama_available
    },
    "qdrant_available": getattr(request.app.state, "qdrant_available", False) if hasattr(request.app.state, "qdrant_available") else _get_qdrant_status(),
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "minimal_mode": bool(getattr(request.app.state, "minimal_mode", False)),
  }

@router.get("/health/circuits", summary="Circuit breaker status (Ollama) (API key required)", response_model=dict, operation_id="circuit_status")
@limiter.limit("30/minute")
async def circuit_status(
  request: Request,
  _: str = Depends(require_api_key),
) -> dict:
  """
  Circuit Breaker status endpoint.

  Returns the current state of all circuit breakers:
  - ollama: LLM inference service (the only wired breaker — the former
    qdrant/http_external entries were decorative and always reported
    closed, WS7-01)

  States:
  - closed: Normal operation
  - open: Service failing, requests rejected
  - half_open: Testing if service recovered
  """
  return {
    "circuits": [
      ollama_breaker.get_status(),
    ],
    "timestamp": datetime.now(timezone.utc).isoformat(),
  }
