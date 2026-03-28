"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: plugins/security/checks/rate_limit_check.py
Description: Security check per validar la configuracio de rate limiting.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import os
import logging
from pathlib import Path
from typing import List, Dict, Any

logger = logging.getLogger(__name__)


class RateLimitCheck:
    """Valida la configuracio de rate limiting."""

    def __init__(self, project_root: Path = None):
        self.project_root = project_root or Path(__file__).parent.parent.parent.parent

    def run(self) -> List[Dict[str, Any]]:
        """Executa els checks de rate limiting."""
        findings = []

        # Check 1: slowapi disponible?
        try:
            import slowapi
            findings.append({
                "check": "rate_limiting",
                "severity": "LOW",
                "title": "Rate limiting library available",
                "description": f"slowapi {slowapi.__version__ if hasattr(slowapi, '__version__') else 'installed'} is available.",
                "recommendation": None
            })
        except ImportError:
            findings.append({
                "check": "rate_limiting",
                "severity": "HIGH",
                "title": "Rate limiting library not installed",
                "description": "slowapi package not found. Rate limiting is disabled.",
                "recommendation": "Install slowapi: pip install slowapi"
            })

        # Check 2: Limits configurats
        global_limit = os.getenv("NEXE_RATE_LIMIT_GLOBAL", "")
        if not global_limit:
            findings.append({
                "check": "rate_limiting",
                "severity": "LOW",
                "title": "Using default global rate limit",
                "description": "NEXE_RATE_LIMIT_GLOBAL not set. Default 100/minute will be used.",
                "recommendation": "Set NEXE_RATE_LIMIT_GLOBAL for custom limits"
            })

        # Check 3: Rate limit tracker funcional?
        try:
            from plugins.security.core.rate_limiting import RateLimitTracker
            tracker = RateLimitTracker()
            findings.append({
                "check": "rate_limiting",
                "severity": "LOW",
                "title": "Rate limit tracker operational",
                "description": "Advanced rate limiting with per-IP/key tracking is available.",
                "recommendation": None
            })
        except Exception as e:
            findings.append({
                "check": "rate_limiting",
                "severity": "MEDIUM",
                "title": "Rate limit tracker not available",
                "description": f"Advanced rate limiting unavailable: {e}",
                "recommendation": "Check plugins/security/core/rate_limiting.py"
            })

        # Check 4: Limits de produccio
        nexe_env = os.getenv("NEXE_ENV", "development").lower()
        health_limit = os.getenv("NEXE_RATE_LIMIT_HEALTH", "1000/minute")
        if nexe_env == "production":
            try:
                count = int(health_limit.split("/")[0])
                if count > 500:
                    findings.append({
                        "check": "rate_limiting",
                        "severity": "MEDIUM",
                        "title": "High health endpoint rate limit in production",
                        "description": f"Health endpoint allows {count} requests per minute. Consider lowering.",
                        "recommendation": "Set NEXE_RATE_LIMIT_HEALTH to a lower value"
                    })
            except (ValueError, IndexError):
                pass

        return findings
