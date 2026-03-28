"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/endpoints/chat_engines/routing.py
Description: Engine resolution and routing logic for Chat endpoint.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


def _normalize_engine(engine: Optional[str]) -> Optional[str]:
    if not engine:
        return None
    value = engine.strip().lower()
    if value in {"llama.cpp", "llama-cpp", "llamacpp"}:
        return "llama_cpp"
    return value

def _get_preferred_engine(app_state) -> Optional[str]:
    """
    Get preferred engine from:
    1. NEXE_MODEL_ENGINE env variable (set by installer)
    2. Config file fallback
    """
    # Priority 1: Environment variable (set by installer in .env)
    env_engine = os.environ.get("NEXE_MODEL_ENGINE")
    if env_engine:
        return env_engine

    # Priority 2: Config file
    config = getattr(app_state, "config", {}) or {}
    return config.get("plugins", {}).get("models", {}).get("preferred_engine")

def _engine_available(engine: str, app_state) -> bool:
    modules = getattr(app_state, "modules", {}) or {}
    if engine == "ollama":
        return "ollama_module" in modules
    if engine == "mlx":
        return "mlx_module" in modules
    if engine == "llama_cpp":
        return "llama_cpp_module" in modules
    return False

def _resolve_engine(request_engine: Optional[str], app_state) -> tuple[str, Optional[str]]:
    requested = _normalize_engine(request_engine)
    if requested and requested != "auto":
        return requested, None

    preferred = _normalize_engine(_get_preferred_engine(app_state))
    if preferred and preferred != "auto":
        if _engine_available(preferred, app_state):
            return preferred, None
        logger.warning("Preferred engine '%s' not available, falling back", preferred)
        for candidate in ["mlx", "llama_cpp", "ollama"]:
            if _engine_available(candidate, app_state):
                return candidate, preferred

    for candidate in ["mlx", "llama_cpp", "ollama"]:
        if _engine_available(candidate, app_state):
            return candidate, None

    return "ollama", None
