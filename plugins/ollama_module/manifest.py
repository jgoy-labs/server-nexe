"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy
Location: plugins/ollama_module/manifest.py
Description: Router FastAPI per modul Ollama.
             Lazy initialization to avoid side effects at import.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from core.loader.manifest_base import create_lazy_manifest, install_lazy_manifest

_m = create_lazy_manifest(
    module_path="plugins.ollama_module.module",
    module_class="OllamaModule",
    tags=["ollama", "llm", "chat", "local"],
    compat_aliases={
        "_ollama_module": "instance",
        "get_ollama_module": "instance",
    },
)

install_lazy_manifest(__name__, _m)
