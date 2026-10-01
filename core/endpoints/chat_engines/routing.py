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
from typing import Any, Optional

from fastapi import HTTPException

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

_ENGINE_MODULE_KEYS = {
    "ollama": "ollama_module",
    "mlx": "mlx_module",
    "llama_cpp": "llama_cpp_module",
}


def get_engine_module(engine: str, app_state):
    """The live module instance serving ``engine``, or None.

    #965: the engine-name → module-key mapping lives here and only here.
    ``_engine_available`` below already called itself the single source of truth
    for what runs; anything else that needs the live module (the context-window
    resolver, for one) asks through this instead of keeping its own copy of the
    three names.
    """
    modules = getattr(app_state, "modules", {}) or {}
    key = _ENGINE_MODULE_KEYS.get(engine)
    return modules.get(key) if key else None


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
    if engine == "ollama":
        modules = getattr(app_state, "modules", {}) or {}
        return "ollama_module" in modules
    if engine in ("mlx", "llama_cpp"):
        instance = get_engine_module(engine, app_state)
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
    asked = _normalize_engine(request_engine)
    if not asked or asked == "auto":
        asked = _normalize_engine(_get_preferred_engine(app_state))
    if asked == "auto":
        asked = None

    cascade = resolve_engine_cascade(request_engine, app_state)
    if not cascade:
        # Terminal: nothing is live. Still honest about the switch — report
        # fallback_from unless what was asked for WAS ollama (no real change).
        return "ollama", (asked if asked and asked != "ollama" else None)

    chosen = cascade[0]
    if asked and chosen != asked:
        logger.warning("Engine '%s' not available, falling back to '%s'", asked, chosen)
        return chosen, asked
    return chosen, None


# The order every door falls back through. Was written out three times: here in
# _resolve_engine, again in the /status resolver, and a fourth-name variant in
# the web UI ("mlx_module", "llama_cpp_module", "ollama_module") that also
# carried its own alias table.
ENGINE_CASCADE = ["mlx", "llama_cpp", "ollama"]


def resolve_engine_cascade(request_engine: Optional[str], app_state) -> list:
    """Every engine worth trying for this turn, best first, node-aware.

    F-D block 5: the one ordering both doors use. ``_resolve_engine`` below is
    this list's head plus the fallback bookkeeping — enough for a caller that
    dispatches once. /ui/chat walks the whole list, because an engine that is
    live when the turn starts can still fail halfway through (a corrupt model, a
    machine out of memory), and the chat recovers by moving down it rather than
    dying on the first one.

    Only serviceable engines are returned (``_engine_available``, B260), so a
    module registered with a dead ``_node`` is skipped here instead of being
    dispatched to and crashing. An empty list means nothing is live.
    """
    requested = _normalize_engine(request_engine)
    ordered = []
    if requested and requested != "auto":
        ordered.append(requested)
    else:
        preferred = _normalize_engine(_get_preferred_engine(app_state))
        if preferred and preferred != "auto":
            ordered.append(preferred)
    ordered += [engine for engine in ENGINE_CASCADE if engine not in ordered]
    return [engine for engine in ordered if _engine_available(engine, app_state)]


def iter_live_engines(cascade: list, app_state):
    """Yield ``(engine_name, module)`` for the engines in ``cascade`` that can chat.

    The web UI used to rebuild this by hand on every request: registry lookup →
    ``.instance`` → ``get_module_instance()`` → ``.chat``, five guards deep. The
    loader already did exactly that walk once (``_resolve_plugin_instance``) and
    put the result in ``app.state.modules``, which is what ``get_engine_module``
    reads and what ``_engine_available`` judges. One resolution, one answer:
    before this, /status and /ui/chat could disagree about what was live.
    """
    for engine_name in cascade:
        # Serviceability is checked again here, not only in the cascade that
        # normally feeds this: a caller passing a list it built itself would
        # otherwise get a module with a dead node handed to it, which is the
        # exact dispatch B260 exists to prevent. It costs a dict lookup.
        if not _engine_available(engine_name, app_state):
            logger.warning("Engine %s is not serviceable, skipping", engine_name)
            continue
        module = get_engine_module(engine_name, app_state)
        if module is None:
            logger.warning("Engine %s resolved but has no live module, skipping", engine_name)
            continue
        if not hasattr(module, "chat"):
            logger.warning("Engine %s module has no chat(), skipping", engine_name)
            continue
        yield engine_name, module


def engine_can_continue(module: Any, model_name: Optional[str] = None) -> bool:
    """C4.6 (FD-S6): can this engine RESUME a truncated answer mid-sentence?

    Asked of the module itself (`can_continue(model_name)`), because only the
    engine knows whether its prompt can end inside the last assistant message
    — and for some engines it depends on the model (MLX: text models only).
    A module that does not declare it cannot: guessing here is what used to
    send a Continue to an engine that silently started a new answer.
    """
    check = getattr(module, "can_continue", None)
    if not callable(check):
        return False
    try:
        return bool(check(model_name))
    except Exception:
        logger.debug("can_continue failed; treating the engine as unable to resume", exc_info=True)
        return False


def engine_error_to_http(exc: BaseException, engine_name: str) -> Optional[tuple]:
    """``(status, detail)`` for an error that ends the turn, or None to try the next engine.

    The retry policy, in one place. It used to live spread across four ``except``
    clauses inside the web UI's engine loop, and /v1 had none of it: whatever the
    single resolved engine raised became a 500. Which errors are worth another
    engine is a product decision, not a per-door detail —

    * a bad request (``ValueError``) is bad for every engine: another one would
      reject it the same way, so it ends the turn;
    * an unreachable or slow backend is reported as such rather than silently
      answered by a different model — the user asked for a machine that is down;
    * anything else is this engine failing at this moment (a corrupt model, an
      OOM, a driver), which is exactly what the cascade exists for.
    """
    if isinstance(exc, HTTPException):
        # Already a deliberate HTTP answer (this is how the /v1 forwarders
        # report a backend that is down, 502/503). It is not this engine
        # failing at this moment, and it must reach the client as written —
        # the caller re-raises it untouched. The web UI used to swallow these
        # in its generic `except Exception: continue` and try the next engine,
        # which is why the model-switch validator raises ValueError with the
        # word "not found" instead of the 404 it means.
        return None
    if isinstance(exc, ValueError):
        message = str(exc)
        return (404 if "not found" in message.lower() else 400), message
    if isinstance(exc, ConnectionError):
        return 503, f"Cannot connect to {engine_name}: {exc}"
    if isinstance(exc, TimeoutError):
        return 504, f"Timeout calling {engine_name}: {exc}"
    return None


def should_try_next_engine(exc: BaseException) -> bool:
    """True when the cascade should move on instead of failing the turn."""
    if isinstance(exc, HTTPException):
        return False
    return engine_error_to_http(exc, "") is None


def raise_if_terminal(exc: BaseException, engine_name: str) -> None:
    """Raise the HTTP answer this error deserves, or return so the caller moves
    on to the next engine.

    Both doors do the same two things with a failed engine — decide, then raise
    the right thing — so both live here rather than being re-expressed at each
    call site. An HTTPException is re-raised exactly as it was written: it is
    already the answer, and rewrapping it would lose its status and headers.
    """
    if should_try_next_engine(exc):
        return
    http = engine_error_to_http(exc, engine_name)
    if http is None:
        raise exc
    raise HTTPException(status_code=http[0], detail=http[1])
