"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy
Location: plugins/security/module.py
Description: Modul Security — NexeModule + NexeModuleWithRouter Protocol.
             Gestiona autenticacio, rate limiting, deteccio d'injeccions i escaneig.

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
    Plugin Nexe — Seguretat core.
    Implementa NexeModule + NexeModuleWithRouter.

    Funcionalitats:
    - Autenticacio dual-key (primary + secondary) amb secrets.compare_digest
    - 6 detectors d'injeccio (XSS, SQL, NoSQL, command, path, LDAP)
    - Rate limiting avancat amb RateLimitTracker
    - Sanitizer subplugin amb 69 patrons de jailbreak multiidioma
    - Security logging RFC5424 (IRONCLAD)
    """

    def __init__(self):
        self._initialized = False
        self._router = None

    # --- NexeModule Protocol ---

    @property
    def metadata(self) -> ModuleMetadata:
        return ModuleMetadata(
            name="security",
            version="0.8.2",
            description="Security core: auth, rate limiting, injection detection, scanning",
            author="Jordi Goy",
            module_type="core",
            quadrant="core",
            dependencies=[],
            tags=["security", "auth", "core"],
        )

    async def initialize(self, context: Dict[str, Any]) -> bool:
        """Inicialitzacio via Nexe Launcher"""
        if self._initialized:
            return True

        # Router sempre primer (permet diagnostics encara que falli)
        self._init_router()

        try:
            # Crear directori logs si no existeix
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
                result = sanitizer.is_safe("test input")
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
                sl = get_security_logger()
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
        return self._router

    def get_router_prefix(self) -> str:
        return "/security"

    # --- Router setup ---

    def _init_router(self):
        """Inicialitza router amb endpoints basics (info, health).
        Els endpoints complets es registren a api/routes.py."""
        from .api.routes import create_router
        self._router = create_router(self)

    # --- Metodes publics ---

    def get_info(self) -> Dict[str, Any]:
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
