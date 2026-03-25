"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy
Location: plugins/security/checks/auth_check.py
Description: Security check per validar la configuracio d'autenticacio.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import os
import logging
from pathlib import Path
from typing import List, Dict, Any

logger = logging.getLogger(__name__)


class AuthCheck:
    """Valida la configuracio d'autenticacio del sistema."""

    def __init__(self, project_root: Path = None):
        self.project_root = project_root or Path(__file__).parent.parent.parent.parent

    def run(self) -> List[Dict[str, Any]]:
        """Executa els checks d'autenticacio."""
        findings = []

        # Check 1: API keys configurades?
        primary_key = os.getenv("NEXE_PRIMARY_API_KEY", "")
        secondary_key = os.getenv("NEXE_SECONDARY_API_KEY", "")
        admin_key = os.getenv("NEXE_ADMIN_API_KEY", "")
        dev_mode = os.getenv("NEXE_DEV_MODE", "false").lower() == "true"

        if not primary_key and not admin_key:
            if dev_mode:
                findings.append({
                    "check": "auth_config",
                    "severity": "HIGH",
                    "title": "No API keys configured (dev mode active)",
                    "description": "No API keys configured. Dev mode bypass is active — not safe for production.",
                    "recommendation": "Set NEXE_PRIMARY_API_KEY environment variable"
                })
            else:
                findings.append({
                    "check": "auth_config",
                    "severity": "CRITICAL",
                    "title": "No API keys configured",
                    "description": "No valid API keys found. Server will reject all authenticated requests.",
                    "recommendation": "Set NEXE_PRIMARY_API_KEY environment variable"
                })

        # Check 2: Dev mode en produccio?
        nexe_env = os.getenv("NEXE_ENV", "development").lower()
        if dev_mode and nexe_env == "production":
            findings.append({
                "check": "auth_config",
                "severity": "CRITICAL",
                "title": "Dev mode active in production",
                "description": "NEXE_DEV_MODE=true while NEXE_ENV=production. Auth bypass possible.",
                "recommendation": "Disable NEXE_DEV_MODE in production"
            })

        # Check 3: Remote dev bypass permès?
        allow_remote = os.getenv("NEXE_DEV_MODE_ALLOW_REMOTE", "false").lower() == "true"
        if dev_mode and allow_remote:
            findings.append({
                "check": "auth_config",
                "severity": "HIGH",
                "title": "Remote dev mode bypass enabled",
                "description": "NEXE_DEV_MODE_ALLOW_REMOTE=true allows auth bypass from remote IPs.",
                "recommendation": "Disable NEXE_DEV_MODE_ALLOW_REMOTE"
            })

        # Check 4: Clau secundaria activa (hauria de migrar-se)
        if secondary_key:
            findings.append({
                "check": "auth_config",
                "severity": "LOW",
                "title": "Secondary API key still active",
                "description": "Secondary key should be temporary for rotation. Migrate to primary.",
                "recommendation": "Remove NEXE_SECONDARY_API_KEY after migration"
            })

        # Check 5: Module allowlist en produccio
        approved = os.getenv("NEXE_APPROVED_MODULES", "").strip()
        if nexe_env == "production" and not approved:
            findings.append({
                "check": "auth_config",
                "severity": "HIGH",
                "title": "No module allowlist in production",
                "description": "NEXE_APPROVED_MODULES not set. All modules will be loaded.",
                "recommendation": "Set NEXE_APPROVED_MODULES with approved module list"
            })

        return findings
