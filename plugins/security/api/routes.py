"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: plugins/security/api/routes.py
Description: FastAPI endpoints for the security module.
             Separated from manifest.py to follow the canonical structure.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import FileResponse
from pathlib import Path
import asyncio
import logging

from plugins.security.core.auth import require_api_key
from plugins.security.core.validators import validate_safe_path

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

logger = logging.getLogger(__name__)

MODULE_PATH = Path(__file__).parent.parent
UI_PATH = MODULE_PATH / "ui"


def create_router(module_instance) -> APIRouter:
    """
    Creates the FastAPI router with all security endpoints.

    Args:
        module_instance: SecurityModule instance (to access health_check, get_info)

    Returns:
        Configured APIRouter
    """
    router = APIRouter(prefix="/security")

    @router.get("/health", operation_id="security_health")
    async def health(_: str = Depends(require_api_key)):
        """Health check for the security module. PROTECTED: Requires API key."""
        result = await module_instance.health_check()
        return result.to_dict()

    @router.get("/info", operation_id="security_info")
    async def info(_: str = Depends(require_api_key)):
        """Security module information. PROTECTED: Requires API key."""
        return module_instance.get_info()

    @router.post("/scan", operation_id="security_scan")
    @limiter.limit("2/minute")
    async def run_security_scan(
        request: Request,
        _: str = Depends(require_api_key)
    ):
        """
        Runs a full security scan.
        Discovers and runs all module checks.

        PROTECTED: Requires API key (X-API-Key header)
        Rate limited: 2 requests/minute
        """
        try:
            from plugins.security.checks.auth_check import AuthCheck
            from plugins.security.checks.web_security_check import WebSecurityCheck
            from plugins.security.checks.rate_limit_check import RateLimitCheck

            results = []
            project_root = MODULE_PATH.parent.parent  # server-nexe root

            checks = [
                AuthCheck(project_root=project_root),
                WebSecurityCheck(project_root=project_root),
                RateLimitCheck(project_root=project_root),
            ]
            for check in checks:
                try:
                    if asyncio.iscoroutinefunction(check.run):  # type: ignore[attr-defined]  # checks: all classes have .run() — list[object] by inference
                        check_results = await check.run()  # type: ignore[attr-defined]
                    else:
                        check_results = check.run()  # type: ignore[attr-defined]
                    if isinstance(check_results, list):
                        results.extend(check_results)
                    elif check_results:
                        results.append(check_results)
                except Exception as check_error:
                    logger.warning("Check %s failed: %s", check.__class__.__name__, check_error)

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
            logger.error("Security scan failed: %s", e)
            raise HTTPException(status_code=500, detail=str(e))

    @router.get("/report", operation_id="security_report")
    @limiter.limit("10/minute")
    async def get_security_report(
        request: Request,
        _: str = Depends(require_api_key)
    ):
        """
        Returns the latest security report.

        PROTECTED: Requires API key (X-API-Key header)
        Rate limited: 10 requests/minute
        """
        try:
            return {
                "status": "success",
                "report": {
                    "module": "security",
                    "version": module_instance.metadata.version,
                    "checks_available": ["auth_check", "web_security_check", "rate_limit_check"],
                    "message": "Use POST /security/scan to run a full security scan"
                }
            }
        except Exception as e:
            logger.error("Failed to get security report: %s", e)
            raise HTTPException(status_code=500, detail=str(e))

    @router.get("/ui/assets/{path:path}", operation_id="security_serve_assets")
    async def serve_security_assets(path: str):
        """Serves static assets (CSS, JS, fonts)"""
        assets_base = UI_PATH / "assets"
        safe_path = validate_safe_path(assets_base / path, assets_base)
        return FileResponse(safe_path)

    @router.get("/ui", operation_id="security_serve_ui")
    async def serve_security_ui():
        """Serves the security module UI"""
        ui_file = UI_PATH / "index.html"

        if not ui_file.exists():
            return {
                "message": "Security UI not available. Use the REST API endpoints.",
                "api_endpoints": ["/security/scan", "/security/report"]
            }

        return FileResponse(ui_file, media_type="text/html")

    return router
