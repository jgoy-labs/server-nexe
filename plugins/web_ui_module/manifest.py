"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy
Location: plugins/web_ui_module/manifest.py
Description: Router FastAPI per modul Web UI.
             Lazy initialization to avoid side effects at import.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from core.loader.manifest_base import create_lazy_manifest, install_lazy_manifest

_m = create_lazy_manifest(
    module_path="plugins.web_ui_module.module",
    module_class="WebUIModule",
    tags=["ui", "web", "demo"],
)

install_lazy_manifest(__name__, _m)
