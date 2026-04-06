"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/endpoints/chat_engines/ollama_helpers.py
Description: Shared helpers for Ollama integration.
             Centralises num_ctx auto-detection so both the core chat engine
             (ollama.py) and the plugin module (ollama_module/module.py) use
             exactly the same logic.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import os


def auto_num_ctx() -> int:
    """Auto-detect num_ctx based on system RAM.

    Override with NEXE_OLLAMA_NUM_CTX env var.
    Used by core/endpoints/chat_engines/ollama.py and
    plugins/ollama_module/module.py to avoid duplicated RAM-detection logic.
    """
    explicit = os.environ.get("NEXE_OLLAMA_NUM_CTX")
    if explicit:
        return int(explicit)
    try:
        import psutil
        ram_gb = psutil.virtual_memory().total / (1024 ** 3)
    except ImportError:
        return 4096
    if ram_gb >= 64:
        return 32768
    elif ram_gb >= 32:
        return 16384
    elif ram_gb >= 24:
        return 8192
    elif ram_gb >= 16:
        return 4096
    return 2048
