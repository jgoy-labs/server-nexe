"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: plugins/api_module/manifest.py
Description: Lazy manifest of the API engine module. The core import is
             deferred into a function: a plugin does not pull core at import
             time (layering gate, #471).

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""


def _install() -> None:
    from core.modules.manifest_base import create_lazy_manifest, install_lazy_manifest

    manifest = create_lazy_manifest(
        module_path="plugins.api_module.module",
        module_class="ApiModule",
        tags=["api", "llm", "chat", "cloud"],
    )
    install_lazy_manifest(__name__, manifest)


_install()
