"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: plugins/security/checks/web_security_check.py
Description: Security check to validate web protections (CORS, headers, injections).

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import os
import logging
from pathlib import Path
from typing import List, Dict, Any

logger = logging.getLogger(__name__)


class WebSecurityCheck:
    """Validates web protections of the system."""

    def __init__(self, project_root: Path = None):  # type: ignore[assignment]  # no_implicit_optional
        self.project_root = project_root or Path(__file__).parent.parent.parent.parent

    def run(self) -> List[Dict[str, Any]]:
        """Runs the web security checks."""
        findings = []

        # Check 1: CORS origins configured?
        cors_origins = os.getenv("NEXE_CORS_ORIGINS", "").strip()
        if not cors_origins:
            findings.append({
                "check": "web_security",
                "severity": "MEDIUM",
                "title": "CORS origins not configured",
                "description": "NEXE_CORS_ORIGINS not set. Default CORS policy will be used.",
                "recommendation": "Set NEXE_CORS_ORIGINS to restrict allowed origins"
            })
        elif "*" in cors_origins:
            findings.append({
                "check": "web_security",
                "severity": "HIGH",
                "title": "CORS allows all origins",
                "description": "NEXE_CORS_ORIGINS contains '*'. Any origin can access the API.",
                "recommendation": "Restrict CORS to specific origins"
            })

        # Check 2: Injection detectors available?
        # Defensive imports: validate availability via try/except, F401 noqa.
        try:
            from plugins.security.core.injection_detectors import (  # noqa: F401
                detect_xss_attempt,
                detect_sql_injection,
                detect_command_injection,
            )
            findings.append({
                "check": "web_security",
                "severity": "LOW",
                "title": "Injection detectors operational",
                "description": "XSS, SQL, and command injection detectors are loaded correctly.",
                "recommendation": None  # type: ignore[dict-item]  # "recommendation": None is valid — dict expects str but Optional[str] by design
            })
        except ImportError as e:
            findings.append({
                "check": "web_security",
                "severity": "HIGH",
                "title": "Injection detectors not available",
                "description": f"Failed to load injection detectors: {e}",
                "recommendation": "Check plugins/security/core/injection_detectors.py"
            })

        # Check 3: Sanitizer operational?
        try:
            from plugins.security.sanitizer.module import get_sanitizer
            sanitizer = get_sanitizer()
            sanitizer.is_safe("test")  # Smoke test, return value not stored
            findings.append({
                "check": "web_security",
                "severity": "LOW",
                "title": "Sanitizer operational",
                "description": "Jailbreak and injection sanitizer is functional.",
                "recommendation": None  # type: ignore[dict-item]  # "recommendation": None is valid — dict expects str but Optional[str] by design
            })
        except Exception as e:
            findings.append({
                "check": "web_security",
                "severity": "MEDIUM",
                "title": "Sanitizer not available",
                "description": f"Failed to initialize sanitizer: {e}",
                "recommendation": "Check plugins/security/sanitizer/"
            })

        # Check 4: HTTPS in production?
        nexe_env = os.getenv("NEXE_ENV", "development").lower()
        ssl_cert = os.getenv("NEXE_SSL_CERT", "").strip()
        if nexe_env == "production" and not ssl_cert:
            findings.append({
                "check": "web_security",
                "severity": "MEDIUM",
                "title": "No SSL certificate configured for production",
                "description": "NEXE_SSL_CERT not set in production mode.",
                "recommendation": "Configure SSL/TLS for production deployment"
            })

        return findings
