"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/endpoints/chat_engines/model_switch.py
Description: F-D block 5 — loading a different model on the live engine.

    This was `_switch_engine_model` inside the web UI plugin, with two private
    per-engine helpers beside it that imported MLXConfig and LlamaCppConfig. The
    capability is not the UI's: any door could want it. But it could not simply
    move here, because the core importing a plugin is what the layering gate
    forbids (core → plugins = 0).

    So it moved in two halves. The half that knows what a model of a given kind
    looks like, and how to build that engine's config, went into the engines
    themselves as `switch_model_by_path` — the same shape `get_context_window`
    (#965) already uses. What is left here is the half that is nobody's engine
    in particular: find the file under the models directory, serialise the
    swaps, and ask.

    /v1 does NOT call this. It runs the model that is loaded and reports it
    (B075-C3); giving the API door a per-request model switch is a product
    decision, not a side effect of moving code.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import asyncio
import logging
import weakref
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# One lock per event loop. What it guards is process-global — the engines' own
# class-level singletons — so the lock has to outlive any single router; it used
# to be created inside register_chat_routes, which meant a fresh one for every
# app built. A plain module-level lock would be the other extreme: an
# asyncio.Lock binds to the loop that first awaits it and raises for any other,
# and every TestClient request runs its own loop. Keyed by loop: one lock where
# it matters (the server's single loop), no cross-loop reuse where it would only
# be a crash. Weak keys so finished loops do not pile up.
_SWITCH_LOCKS: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()


def model_switch_lock() -> asyncio.Lock:
    """The lock that serialises model switches on the running loop.

    P0-3 (defense-in-depth): server-nexe is architecturally mono-user
    (workers=1, class-level singletons), so two concurrent requests with
    different `body.model` racing to mutate LlamaCppChatNode._pool /
    MLXChatNode._model is effectively never seen in the field. The lock is a
    breadcrumb for a future multi-user design; the full refactor (multi-pool
    LRU + config_override) is deferred to it.
    """
    loop = asyncio.get_running_loop()
    lock = _SWITCH_LOCKS.get(loop)
    if lock is None:
        lock = asyncio.Lock()
        _SWITCH_LOCKS[loop] = lock
    return lock


def resolve_local_model_path(model_name: str) -> Path:
    """Where `model_name` lives under the models directory.

    Delegates to get_models_dir() so the lookup chain (NEXE_STORAGE_PATH →
    NEXE_DATA_DIR/models → cwd → repo) stays centralised and matches
    routes_auth._resolve_models_dir(). The version before it read
    `NEXE_STORAGE_PATH / "models"` and broke when the env var already pointed at
    the models dir (a user-selected local models folder).
    """
    from core.lifespan import get_server_state
    from core.paths.helpers import get_models_dir

    models_dir = get_models_dir()
    if not models_dir.is_absolute():
        models_dir = Path(get_server_state().project_root) / models_dir
    return models_dir / model_name


async def switch_engine_model(engine: Any, engine_name: str, model_name: str) -> bool:
    """Ask the live engine to load `model_name`, if that means anything to it.

    Returns True when a swap really happened. An engine without the contract
    (Ollama picks its model per request, and so would any engine written before
    this) keeps the model it has and says so in the log — never an exception:
    the turn is still answerable by the loaded model.

    Whatever the engine raises travels up untouched. `switch_model_by_path`
    raising ValueError("... not found") is deliberate — the caller maps it to a
    clean 404, which is how the ghost-directory incident (8 GB M1, 2026-07-23)
    stopped being a raw FileNotFoundError mid-answer.
    """
    switcher = getattr(engine, "switch_model_by_path", None)
    if not callable(switcher):
        logger.info(
            "Engine %s does not switch models per request; keeping the loaded one",
            engine_name,
        )
        return False
    return bool(switcher(resolve_local_model_path(model_name)))
