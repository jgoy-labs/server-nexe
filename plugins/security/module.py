"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: plugins/security/module.py
Description: Security Module — NexeModule + NexeModuleWithRouter Protocol.
             Manages authentication, rate limiting, injection detection and scanning.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import logging
from typing import Dict, Any
from pathlib import Path

from fastapi import APIRouter
from core.loader.protocol import ModuleMetadata, HealthResult, HealthStatus

logger = logging.getLogger(__name__)

MODULE_PATH = Path(__file__).parent


class SecurityModule:
    """
    Nexe Plugin — Core security.
    Implements NexeModule + NexeModuleWithRouter.

    Features:
    - Dual-key authentication (primary + secondary) with secrets.compare_digest
    - 6 injection detectors (XSS, SQL, NoSQL, command, path, LDAP)
    - Advanced rate limiting with RateLimitTracker
    - Sanitizer subplugin with 69 multilingual jailbreak patterns
    - Security logging RFC5424 (IRONCLAD)
    """

    def __init__(self):
        self._initialized = False
        self._router = None

    # --- NexeModule Protocol ---

    @property
    def metadata(self) -> ModuleMetadata:
        """Return static module metadata for the security plugin."""
        return ModuleMetadata(
            name="security",
            version="0.9.1",
            description="Security core: auth, rate limiting, injection detection, scanning",
            author="Jordi Goy",
            module_type="core",
            quadrant="core",
            dependencies=[],
            tags=["security", "auth", "core"],
        )

    async def initialize(self, context: Dict[str, Any]) -> bool:
        """Initialization via Nexe Launcher"""
        if self._initialized:
            return True

        # Router always first (allows diagnostics even if it fails)
        self._init_router()

        try:
            # Create logs directory if it doesn't exist
            log_path = MODULE_PATH.parent.parent / "storage" / "system-logs" / "security"
            log_path.mkdir(parents=True, exist_ok=True)

            self._initialized = True
            logger.info("SecurityModule initialized successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to initialize SecurityModule: {e}")
            return False

    async def shutdown(self) -> None:
        """Cleanup — idempotent"""
        self._initialized = False

    async def health_check(self) -> HealthResult:
        """Check security module health: auth config, sanitizer, and IRONCLAD logger."""
        if not self._initialized:
            return HealthResult(
                status=HealthStatus.UNKNOWN,
                message="Module not initialized"
            )

        try:
            checks = []

            # Check 1: auth config
            try:
                from .core.auth_config import load_api_keys
                keys = load_api_keys()
                has_keys = keys.has_any_valid_key
                checks.append({
                    "name": "auth_config",
                    "status": "ok" if has_keys else "warning",
                    "message": "API keys configured" if has_keys else "No valid API keys"
                })
            except Exception as e:
                checks.append({
                    "name": "auth_config",
                    "status": "error",
                    "message": str(e)
                })

            # Check 2: sanitizer
            try:
                from .sanitizer.module import get_sanitizer
                sanitizer = get_sanitizer()
                # Side-effect: probe call ensures the sanitizer responds.
                sanitizer.is_safe("test input")
                checks.append({
                    "name": "sanitizer",
                    "status": "ok",
                    "message": "Sanitizer operational"
                })
            except Exception as e:
                checks.append({
                    "name": "sanitizer",
                    "status": "error",
                    "message": str(e)
                })

            # Check 3: security_logger
            try:
                from .security_logger import get_security_logger
                # Side-effect: lookup confirms the logger is registered.
                get_security_logger()
                checks.append({
                    "name": "security_logger",
                    "status": "ok",
                    "message": "IRONCLAD logger operational"
                })
            except Exception as e:
                checks.append({
                    "name": "security_logger",
                    "status": "error",
                    "message": str(e)
                })

            has_errors = any(c["status"] == "error" for c in checks)
            has_warnings = any(c["status"] == "warning" for c in checks)

            if has_errors:
                status = HealthStatus.DEGRADED
                message = "Security module degraded"
            elif has_warnings:
                status = HealthStatus.HEALTHY
                message = "Security module operational (with warnings)"
            else:
                status = HealthStatus.HEALTHY
                message = "Security module fully operational"

            return HealthResult(
                status=status,
                message=message,
                details={"initialized": True},
                checks=checks
            )
        except Exception as e:
            return HealthResult(
                status=HealthStatus.UNHEALTHY,
                message=str(e)
            )

    # --- NexeModuleWithRouter ---

    def get_router(self) -> APIRouter:
        """Return the FastAPI router for security endpoints."""
        return self._router

    def get_router_prefix(self) -> str:
        """Return the URL prefix for security routes."""
        return "/security"

    # --- Router setup ---

    def _init_router(self):
        """Initializes router with basic endpoints (info, health).
        Full endpoints are registered in api/routes.py."""
        from .api.routes import create_router
        self._router = create_router(self)

    # --- Public methods ---

    def get_info(self) -> Dict[str, Any]:
        """Return module metadata including available security endpoints."""
        return {
            "name": self.metadata.name,
            "version": self.metadata.version,
            "description": self.metadata.description,
            "initialized": self._initialized,
            "type": self.metadata.module_type,
            "endpoints": [
                "/security/health",
                "/security/info",
                "/security/scan",
                "/security/report",
                "/security/ui",
            ],
        }
