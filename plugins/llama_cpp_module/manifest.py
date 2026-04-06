"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: plugins/llama_cpp_module/manifest.py
Description: Lazy manifest for the Llama.cpp module (Universal GGUF).
             Normalitzat al patro create_lazy_manifest / install_lazy_manifest.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from core.loader.manifest_base import create_lazy_manifest, install_lazy_manifest

_m = create_lazy_manifest(
    module_path="plugins.llama_cpp_module.module",
    module_class="LlamaCppModule",
    tags=["llama-cpp", "gguf", "llm"],
)

install_lazy_manifest(__name__, _m)
