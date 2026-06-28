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
from typing import Optional

logger = logging.getLogger(__name__)


def _normalize_engine(engine: Optional[str]) -> Optional[str]:
    """Normalize engine name to its canonical snake_case form."""
    if not engine:
        return None
    value = engine.strip().lower()
    if value in {"llama.cpp", "llama-cpp", "llamacpp"}:
        return "llama_cpp"
    return value

def _get_preferred_engine(app_state) -> Optional[str]:
    """
    Get preferred engine from:
    1. Runtime override / NEXE_MODEL_ENGINE env (live UI selection or installer-set env)
    2. Config file fallback
    """
    # Priority 1: Runtime override > env var.
    from core.runtime_state import get_with_env_fallback
    env_engine = get_with_env_fallback("NEXE_MODEL_ENGINE")
    if env_engine:
        return env_engine

    # Priority 2: Config file
    config = getattr(app_state, "config", {}) or {}
    return config.get("plugins", {}).get("models", {}).get("preferred_engine")

def _engine_available(engine: str, app_state) -> bool:
    """Check whether the given engine is loaded AND serviceable (node-aware).

    B260: a present dict key is not enough for the single-model engines
    (mlx/llama_cpp). A module can be registered with a dead ``_node`` (e.g.
    pre-onboarding, or a loader that did not pop a failed module); dispatching
    to it raises and the forward-layer falls back to Ollama, silently skipping
    another live engine. We therefore require a live ``_node`` for mlx/llama_cpp.
    Ollama has no ``_node`` and stays key-presence (reachability is handled
    downstream). This is the single source of truth shared by chat routing and
    ``/status`` (root.py), so the two can never disagree on what runs.
    """
    modules = getattr(app_state, "modules", {}) or {}
    if engine == "ollama":
        return "ollama_module" in modules
    if engine == "mlx":
        instance = modules.get("mlx_module")
        return instance is not None and getattr(instance, "_node", None) is not None
    if engine == "llama_cpp":
        instance = modules.get("llama_cpp_module")
        return instance is not None and getattr(instance, "_node", None) is not None
    return False

def _resolve_engine(request_engine: Optional[str], app_state) -> tuple[str, Optional[str]]:
    """Resolve the engine to use, returning (engine, fallback_from) tuple.

    B260: availability is node-aware (``_engine_available``) and the
    mlx→llama_cpp→ollama cascade is the single fallback mechanism. An explicit
    engine that is not serviceable degrades GRACEFULLY through the cascade
    (reporting the requested engine as ``fallback_from``) instead of being
    dispatched blindly and crashing into the fixed Ollama fallback.
    """
    requested = _normalize_engine(request_engine)
    if requested and requested != "auto":
        if _engine_available(requested, app_state):
            return requested, None
        logger.warning("Requested engine '%s' not available, falling back", requested)
        for candidate in ["mlx", "llama_cpp", "ollama"]:
            if candidate != requested and _engine_available(candidate, app_state):
                return candidate, requested
        # Terminal: nothing else is live either. Still honest about the switch —
        # report fallback_from unless the request WAS ollama (no real change).
        return "ollama", (requested if requested != "ollama" else None)

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
