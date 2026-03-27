"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy
Location: plugins/security/manifest.py
Description: Router FastAPI per modul security.
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

# ─── Retrocompatibilitat amb codi i tests existents ───
# El manifest.py antic exportava aquests noms directament.
# Els mantenim com a facades lazy per no trencar imports existents.

from .module import SecurityModule  # noqa: E402,F401

MODULE_NAME = "security"

MODULE_METADATA = {
    "name": MODULE_NAME,
    "version": "0.8.2",
    "description": "Security scanning and validation module",
    "routers": ["router_public"],
    "auto_discover": True
}

try:
    from core.dependencies import limiter  # noqa: E402,F401
    RATE_LIMITING_AVAILABLE = True
except ImportError:
    RATE_LIMITING_AVAILABLE = False


def init_security_module():
    """Retrocompat: inicialitza el modul security."""
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
