"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: plugins/security/manifest.py
Description: FastAPI router for the security module.
             Lazy initialization to avoid side effects at import.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from core.loader.manifest_base import create_lazy_manifest, install_lazy_manifest

_m = create_lazy_manifest(
    module_path="plugins.security.module",
    module_class="SecurityModule",
    tags=["security"],
    compat_aliases={
        "module_instance": "instance",
    },
)

# ─── Backward compatibility with existing code and tests ───
# The old manifest.py exported these names directly.
# We keep them as lazy facades to avoid breaking existing imports.

from .module import SecurityModule  # noqa: E402,F401

MODULE_NAME = "security"

MODULE_METADATA = {
    "name": MODULE_NAME,
    "version": "0.9.1",
    "description": "Security scanning and validation module",
    "routers": ["router_public"],
    "auto_discover": True
}

# finding #473: this try/except is retro-compat (keep the exported name resolvable),
# NOT a cycle break — it pairs with the optional import in core/dependencies.py and
# is covered by tests. No import-deadlock risk.
try:
    from core.dependencies import limiter  # noqa: E402,F401
    RATE_LIMITING_AVAILABLE = True
except ImportError:
    RATE_LIMITING_AVAILABLE = False


def init_security_module():
    """Retrocompat: initializes the security module."""
    import logging
    from pathlib import Path
    _logger = logging.getLogger(__name__)
    _logger.info("Security module initialized: %s v%s", MODULE_NAME, MODULE_METADATA['version'])
    log_path = Path(__file__).parent.parent.parent / "storage" / "system-logs" / MODULE_NAME
    log_path.mkdir(parents=True, exist_ok=True)
    return MODULE_METADATA


install_lazy_manifest(__name__, _m, extra_attrs={
    "SecurityModule": SecurityModule,
    "MODULE_NAME": MODULE_NAME,
    "MODULE_METADATA": MODULE_METADATA,
    "RATE_LIMITING_AVAILABLE": RATE_LIMITING_AVAILABLE,
    "init_security_module": init_security_module,
})
