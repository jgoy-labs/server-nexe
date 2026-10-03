"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: plugins/security/checks/web_security_check.py
Description: Security check to validate web protections (CORS, headers, injections).

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import logging
from pathlib import Path
from typing import List, Dict, Any

logger = logging.getLogger(__name__)


class WebSecurityCheck:
    """Validates web protections of the system."""

    def __init__(self, project_root: Path = None):  # type: ignore[assignment]  # no_implicit_optional
        self.project_root = project_root or Path(__file__).parent.parent.parent.parent

    def _effective_cors_origins(self) -> List[str]:
        """The origins that WIN, in the same order the server applies them.

        #865: this check read `NEXE_CORS_ORIGINS`, a variable that does not
        exist anywhere in the product — it audited a ghost and said "not
        configured" even when server.toml had CORS restricted (and it would never
        have seen a real `cors_origins = ["*"]`). The real source is
        `core/middleware.py:setup_cors`: in sidecar mode
        `SidecarConfig.cors_origins` wins (the Tauri origins are in there) and, otherwise,
        `[core.server].cors_origins` from server.toml.

        No new env var is added: a second source of truth
        is exactly what #918 just decided to avoid.
        """
        try:
            from core.sidecar_config import get_sidecar_config
            sidecar_cfg = get_sidecar_config()
            if sidecar_cfg.is_sidecar:
                return list(sidecar_cfg.cors_origins)
        except Exception as e:
            # Same defensive rule as setup_cors: if SidecarConfig cannot be
            # read, fall back to server.toml instead of leaving the check blind.
            logger.debug("CORS check: SidecarConfig unavailable, using server.toml: %s", e)

        from core.config import load_config
        config = load_config(project_root=self.project_root)
        server_cfg = config.get("core", {}).get("server", {})
        return list(server_cfg.get("cors_origins") or [])

    def run(self) -> List[Dict[str, Any]]:
        """Runs the web security checks."""
        findings = []

        # Check 1: CORS origins configured? (read from the source that wins)
        cors_origins = self._effective_cors_origins()
        if not cors_origins:
            findings.append({
                "check": "web_security",
                "severity": "MEDIUM",
                "title": "CORS origins not configured",
                "description": "No cors_origins in the effective configuration; no cross-origin caller is allowed.",
                "recommendation": "Set [core.server].cors_origins in server.toml"
            })
        elif "*" in cors_origins:
            findings.append({
                "check": "web_security",
                "severity": "HIGH",
                "title": "CORS allows all origins",
                "description": "The effective cors_origins contains '*'. Any origin can access the API.",
                "recommendation": "Restrict [core.server].cors_origins to specific origins"
            })

        # Check 2: Injection detectors available?
        # Defensive imports: validate availability via try/except, F401 noqa.
        try:
            from core.security.injection_detectors import (  # noqa: F401
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

        # #865: there used to be a "Check 4: HTTPS in production?" that required
        # `NEXE_SSL_CERT`. Removed: the product is local-first on loopback and
        # serves TLS nowhere — zero certificate or private-key parameters
        # in the whole product tree, which is watched by
        # tests/plugins/security/test_g16_cors_ssl_real_source.py (the exact
        # names live there on purpose: written here, the check would report
        # itself). A check that demands a certificate the product cannot
        # have is noise that hides the real findings.

        return findings
