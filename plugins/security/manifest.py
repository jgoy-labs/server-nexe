"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: plugins/security/manifest.py
Description: FastAPI manifest for the Security module exposing REST endpoints for security scanning.

www.jgoy.net
────────────────────────────────────
"""

from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import FileResponse
from pathlib import Path
import logging

from plugins.security.core.auth import require_api_key
from plugins.security.core.validators import validate_safe_path
from personality.i18n.resolve import t_modular
try:
  from core.dependencies import limiter
  RATE_LIMITING_AVAILABLE = True
except ImportError:
  class NoOpLimiter:
    def limit(self, *args, **kwargs):
      def decorator(func):
        return func
      return decorator
  limiter = NoOpLimiter()
  RATE_LIMITING_AVAILABLE = False

MODULE_PATH = Path(__file__).parent
MODULE_NAME = "security"
UI_PATH = MODULE_PATH / "ui"

MODULE_METADATA = {
  "name": MODULE_NAME,
  "version": "1.0.0",
  "description": "Security scanning and validation module",
  "routers": ["router_public"],
  "auto_discover": True
}

router_public = APIRouter(prefix="/security", tags=["security"])

logger = logging.getLogger(__name__)

def _t_log(key: str, fallback: str, **kwargs) -> str:
  return t_modular(f"security.logs.{key}", fallback, **kwargs)

class SecurityModule:
  """Simple instance for registration and health."""
  def __init__(self, metadata: dict):
    self.name = metadata.get("name", "security")
    self.version = metadata.get("version", "1.0.0")

  def get_health(self):
    return {
      "status": "healthy",
      "module": self.name,
      "version": self.version,
    }

module_instance = SecurityModule(MODULE_METADATA)

def get_module_instance():
  return module_instance

@router_public.get("/health")
async def health():
  """Health check for the security module."""
  return {
    "status": "healthy",
    "module": MODULE_NAME,
    "version": MODULE_METADATA["version"]
  }

@router_public.get("/info")
async def info():
  """Security module information."""
  return {
    "name": MODULE_NAME,
    "description": MODULE_METADATA["description"],
    "version": MODULE_METADATA["version"],
    "endpoints": [
      "/security/health",
      "/security/info",
      "/security/scan",
      "/security/report"
    ]
  }

@router_public.post("/scan")
@limiter.limit("2/minute")
async def run_security_scan(
  request: Request,
  _: str = Depends(require_api_key)
):
  """
  Run a full security scan.
  Discover and execute all module checks.

  🔒 PROTECTED: Requires API key (X-API-Key header)
  ⏱️ Rate limited: 2 requests/minute
  """
  try:
    from .checks.auth_check import AuthCheck
    from .checks.web_security_check import WebSecurityCheck
    from .checks.rate_limit_check import RateLimitCheck

    results = []
    project_root = Path(__file__).parent.parent.parent  # server.nexe root

    # Execute all security checks (each may need project_root)
    checks = [
      AuthCheck(project_root=project_root),
      WebSecurityCheck(project_root=project_root),
      RateLimitCheck(project_root=project_root),
    ]
    for check in checks:
      try:
        import asyncio
        if asyncio.iscoroutinefunction(check.run):
          loop = asyncio.new_event_loop()
          try:
            asyncio.set_event_loop(loop)
            check_results = loop.run_until_complete(check.run())
          finally:
            loop.close()
            asyncio.set_event_loop(None)
        else:
          check_results = check.run()
        if isinstance(check_results, list):
          results.extend(check_results)
        elif check_results:
          results.append(check_results)
      except Exception as check_error:
        logger.warning(
          _t_log(
            "check_failed",
            "Check {check} failed: {error}",
            check=check.__class__.__name__,
            error=str(check_error),
          )
        )

    critical = [r for r in results if r.get("severity") == "CRITICAL"]
    high = [r for r in results if r.get("severity") == "HIGH"]
    medium = [r for r in results if r.get("severity") == "MEDIUM"]
    low = [r for r in results if r.get("severity") == "LOW"]

    return {
      "status": "completed",
      "summary": {
        "total_findings": len(results),
        "critical": len(critical),
        "high": len(high),
        "medium": len(medium),
        "low": len(low)
      },
      "findings": {
        "critical": critical,
        "high": high,
        "medium": medium,
        "low": low
      }
    }
  except Exception as e:
    logger.error(
      _t_log(
        "scan_failed",
        "Security scan failed: {error}",
        error=str(e),
      )
    )
    raise HTTPException(status_code=500, detail=str(e))

@router_public.get("/report")
@limiter.limit("10/minute")
async def get_security_report(
  request: Request,
  _: str = Depends(require_api_key)
):
  """
  Return the latest security report.

  🔒 PROTECTED: Requires API key (X-API-Key header)
  ⏱️ Rate limited: 10 requests/minute
  """
  try:
    return {
      "status": "success",
      "report": {
        "module": MODULE_NAME,
        "version": MODULE_METADATA["version"],
        "checks_available": ["auth_check", "web_security_check", "rate_limit_check"],
        "message": t_modular(
          "security.api.scan_hint",
          "Use POST /security/scan to run a full security scan"
        )
      }
    }
  except Exception as e:
    logger.error(
      _t_log(
        "report_failed",
        "Failed to get security report: {error}",
        error=str(e),
      )
    )
    raise HTTPException(status_code=500, detail=str(e))

@router_public.get("/ui/assets/{path:path}")
async def serve_security_assets(path: str):
  """
  Serve static assets (CSS, JS, fonts).
  """
  assets_base = UI_PATH / "assets"
  safe_path = validate_safe_path(assets_base / path, assets_base)

  return FileResponse(safe_path)

@router_public.get("/ui")
async def serve_security_ui():
  """Serve the security module UI (optional)."""
  ui_file = UI_PATH / "index.html"

  if not ui_file.exists():
    return {
      "message": t_modular(
        "security.ui.not_implemented",
        "Security UI not implemented yet"
      ),
      "api_endpoints": ["/security/scan", "/security/report"]
    }

  return FileResponse(ui_file, media_type="text/html")

def init_security_module():
  """Initialize the security module."""
  logger.info(
    _t_log(
      "initialized",
      "Security module initialized: {name} v{version}",
      name=MODULE_NAME,
      version=MODULE_METADATA["version"],
    )
  )

  log_path = MODULE_PATH.parent.parent.parent / "storage" / "system-logs" / MODULE_NAME
  log_path.mkdir(parents=True, exist_ok=True)

  return MODULE_METADATA

__all__ = [
  "router_public",
  "MODULE_METADATA",
  "init_security_module",
]
