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
from dataclasses import dataclass
from typing import Any, Optional

import httpx
from fastapi import HTTPException

from core.providers.cloud import CLOUD_ENGINE, CloudRefusal, require_cloud_request

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EngineEntry:
    """One engine, once: every table that used to be written by hand is read off these."""

    name: str                       # canonical (snake_case): what the cascade, the metrics and the headers say
    module_key: str                 # where the loader puts its live module (`app.state.modules`)
    ui_id: str                      # the web dropdown's spelling of the backend
    in_cascade: bool                # a step of the automatic fallback chain (an opt-in engine is not)
    in_process: bool = False        # runs inside this process: needs a live `_node`, and is told to stop by `cancel_event`
    cloud: bool = False             # a hosted engine: what it is sent leaves the machine (the API)
    aliases: tuple = ()             # other spellings a request may use


#: The ONE table of engines (phase 3 of the API providers). `ENGINE_CASCADE`,
#: `ENGINE_MODULE_KEYS`, the aliases, the web dropdown's ids and `/status`'s
#: availability are all read off it; a fifth hand-written copy is what
#: `tests/core/test_engine_table.py` exists to refuse. The order of the entries
#: with `in_cascade` is the order of the fallback chain.
#:
#: The API engine is in the table so that it can be FOUND and named, and it is
#: not `in_cascade`: no turn ever falls to it, and it never gets a fallback.
ENGINE_TABLE: tuple = (
    EngineEntry("mlx", "mlx_module", "mlx", in_cascade=True, in_process=True),
    EngineEntry("llama_cpp", "llama_cpp_module", "llamacpp", in_cascade=True, in_process=True,
                aliases=("llama.cpp", "llama-cpp", "llamacpp")),
    EngineEntry("ollama", "ollama_module", "ollama", in_cascade=True),
    EngineEntry(CLOUD_ENGINE, "api_module", "api", in_cascade=False, cloud=True),
)


def engine_entry(name: Optional[str]) -> Optional[EngineEntry]:
    """The table's entry for a canonical engine name, or None."""
    return next((entry for entry in ENGINE_TABLE if entry.name == name), None)


def engine_is_cloud(engine: Any) -> bool:
    """Does what this engine is sent leave the machine?

    Asked of an engine NAME (`/v1` carries names) or of the live module (the web
    door carries the module: a hosted engine says so with `runs_in_the_cloud`).
    Exactly `True`, never truthiness: a test double that answers any attribute
    must not be taken for a provider."""
    if isinstance(engine, str):
        entry = engine_entry(_normalize_engine(engine))
        return entry is not None and entry.cloud
    return getattr(engine, "runs_in_the_cloud", False) is True


def _normalize_engine(engine: Optional[str]) -> Optional[str]:
    """Normalize engine name to its canonical snake_case form."""
    if not engine or not isinstance(engine, str):
        return None
    value = engine.strip().lower()
    for entry in ENGINE_TABLE:
        if value in entry.aliases:
            return entry.name
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

#: engine name → the key of its module (`app.state.modules`). The API engine is
#: named here so its module can be found; it is not in `ENGINE_CASCADE`.
ENGINE_MODULE_KEYS = {entry.name: entry.module_key for entry in ENGINE_TABLE}


def cloud_gate(request: Any) -> None:
    """Raise the HTTP answer of a `/v1` request that may not leave this machine.

    One rule for every caller at this door: the switch, a provider that owns the
    model and has its key, and the request's own `nexe_cloud_consent` (the key of
    the provider it agrees to, for this request only). The body of the refusal
    says why (`code`), never a key."""
    try:
        require_cloud_request(getattr(request, "model", None), getattr(request, "nexe_cloud_consent", None))
    except CloudRefusal as refusal:
        raise HTTPException(status_code=refusal.status, detail=refusal.detail()) from None


def cloud_request_ok(body: Any) -> bool:
    """Does this `/v1` body ask for the API engine, and may it have it?

    True: it asks for the API and the gate passed. False: it asks for anything
    else, which is never the API (the engine in the body is the only way in: an
    environment preference or "auto" never reaches the cloud). A request that
    asks for the API and may not raises (`cloud_gate`)."""
    if _normalize_engine(getattr(body, "engine", None)) != CLOUD_ENGINE:
        return False
    cloud_gate(body)
    return True


def bind_to_model(module: Any, model: Optional[str]) -> Any:
    """The engine as ONE turn sees it.

    A hosted engine answers its window and its sight per model, and those
    questions carry no model: it hands back a view bound to the turn's own
    (`for_model`), so two turns never read each other's. Every other engine is
    returned as it is. Only a module that says `runs_in_the_cloud` is asked: a
    test double that answers any attribute is not."""
    if getattr(module, "runs_in_the_cloud", False) is True:
        binder = getattr(module, "for_model", None)
        if callable(binder):
            return binder(model)
    return module


def get_engine_module(engine: str, app_state):
    """The live module instance serving ``engine``, or None.

    #965: the engine-name → module-key mapping lives here and only here.
    ``_engine_available`` below already called itself the single source of truth
    for what runs; anything else that needs the live module (the context-window
    resolver, for one) asks through this instead of keeping its own copy of the
    three names.
    """
    modules = getattr(app_state, "modules", {}) or {}
    key = ENGINE_MODULE_KEYS.get(engine)
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
    entry = engine_entry(engine)
    if entry is None:
        return False
    if entry.in_process:
        instance = get_engine_module(engine, app_state)
        return instance is not None and getattr(instance, "_node", None) is not None
    # Ollama has no `_node`: key presence, reachability is handled downstream.
    # The API engine is the same: LOADED is not ALLOWED — the switch, the key
    # and the consent are the cloud gate's (core/providers/cloud.py), asked by
    # the door.
    modules = getattr(app_state, "modules", {}) or {}
    return entry.module_key in modules

def _resolve_engine(
    request_engine: Optional[str], app_state, *, cloud_ok: bool = False,
) -> tuple[str, Optional[str]]:
    """Resolve the engine to use, returning (engine, fallback_from) tuple.

    B260: availability is node-aware (``_engine_available``) and the
    mlx→llama_cpp→ollama cascade is the single fallback mechanism. An explicit
    engine that is not serviceable degrades GRACEFULLY through the cascade
    (reporting the requested engine as ``fallback_from``) instead of being
    dispatched blindly and crashing into the fixed Ollama fallback.

    The API engine (``CLOUD_ENGINE``) is not part of that: asked for explicitly
    it is answered by itself or refused, never by another engine. ``cloud_ok``
    is the caller saying the cloud gate was passed for this request (the switch,
    a model and key a provider owns, the request's own consent); without it the
    answer is a 400, and a gate that passed with the module not loaded is a 503.
    """
    if _normalize_engine(request_engine) == CLOUD_ENGINE:
        if not cloud_ok:
            raise HTTPException(status_code=400, detail="The API engine needs the cloud gate on this endpoint")
        if not _engine_available(CLOUD_ENGINE, app_state):
            raise HTTPException(status_code=503, detail="The API engine is not loaded on this server")
        return CLOUD_ENGINE, None
    asked = asked_engine(request_engine, app_state)

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


def asked_engine(request_engine: Optional[str], app_state) -> Optional[str]:
    """The engine the client asked for, by its canonical name: the request's,
    else the configured preference. None when it named none ("auto", nothing,
    or the API as a mere preference — it is ignored by the cascade too, and
    not reported as a fallback): then the first live engine is the one it gets."""
    asked = _normalize_engine(request_engine)
    if asked == CLOUD_ENGINE:
        return CLOUD_ENGINE
    if not asked or asked == "auto":
        asked = _normalize_engine(_get_preferred_engine(app_state))
    if asked == "auto" or asked == CLOUD_ENGINE:
        return None
    return asked


def in_reserve(index: int, name: str, asked: Optional[str]) -> bool:
    """Is this engine a fallback — not the one the client asked for (B2, N5)?

    By what was asked, not by position: when the engine asked for is not live,
    the first live one is a fallback too (it runs its own model, a missing
    model moves on from it). When the client named no engine, the first of
    the cascade is the one it gets."""
    return name != asked if asked else index > 0


# The order every door falls back through. Was written out three times: here in
# _resolve_engine, again in the /status resolver, and a fourth-name variant in
# the web UI ("mlx_module", "llama_cpp_module", "ollama_module") that also
# carried its own alias table.
ENGINE_CASCADE = [entry.name for entry in ENGINE_TABLE if entry.in_cascade]


def resolve_engine_cascade(request_engine: Optional[str], app_state, *, cloud_ok: bool = False) -> list:
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

    The API engine (``CLOUD_ENGINE``) is an opt-in, never a step down: it is
    returned ONLY when it is the explicit request AND the caller has passed
    the cloud gate (``cloud_ok``), and then it is returned ALONE — a provider
    that fails is not answered by a local model the user did not ask for, and
    a local request never grows an API fallback. A preference read from the
    environment is not an explicit request, so it is ignored for this engine.
    """
    requested = _normalize_engine(request_engine)
    if requested == CLOUD_ENGINE:
        return [CLOUD_ENGINE] if cloud_ok and _engine_available(CLOUD_ENGINE, app_state) else []
    ordered = []
    if requested and requested != "auto":
        ordered.append(requested)
    else:
        preferred = _normalize_engine(_get_preferred_engine(app_state))
        if preferred and preferred != "auto" and preferred != CLOUD_ENGINE:
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


def engine_takes_model(module: Any) -> bool:
    """Does this engine's `chat` take the model per request (Ollama's style)?

    The same test `start_engine_call` makes to pick the call shape, asked in one
    place for the internal steps (compaction, image description) that used to
    recognise Ollama by its class name and so called every other engine like an
    in-process one. An engine whose signature cannot be read takes none.
    """
    import inspect

    try:
        return "model" in inspect.signature(module.chat).parameters
    except (AttributeError, TypeError, ValueError):
        return False


def engine_can_see_images(module: Any) -> Optional[bool]:
    """#1035: can the model this engine runs read an image?

    Asked of an engine that answers with a model it chose itself (a fallback
    runs the one it has loaded), so a text model is never handed a turn with
    a picture to answer as if it saw it. `None` when the module does not say:
    an engine that takes its model per request (Ollama) is given the one
    requested, and is left to it, as before. A check that raises says no.
    """
    check = getattr(module, "can_see_images", None)
    if not callable(check):
        return None
    try:
        return bool(check())
    except Exception:
        logger.debug("can_see_images failed; treating the engine as unable to see", exc_info=True)
        return False


#: What an engine's failure MEANS, whoever raised it (C4.8 N5). The cascade's
#: policy reads this and never the exception's class: the same event used to be
#: final or worth another engine depending on who raised it — Ollama down was a
#: retry on the web (the module's `httpx.ConnectError`) and a final 503 at /v1
#: (the forwarder's HTTPException); a timeout was final from a builtin
#: `TimeoutError` and retried from httpx's.
BAD_REQUEST = "bad_request"  # the request is wrong: every engine would refuse it
NOT_FOUND = "not_found"      # this engine has no such model
DOWN = "down"                # unreachable, too slow, or failing now (a 5xx, a 401, out of memory, a crash)
REFUSED = "refused"          # a deliberate no, said by the error itself (`fault`): the API's refused key
FAULTS = (BAD_REQUEST, NOT_FOUND, DOWN, REFUSED)


def _fault_of_status(status: int) -> str:
    """An HTTP status, read for what it says about the engine that sent it: a
    missing model, a bad request, or an engine failing. A 401/403 from an
    engine (Ollama behind a proxy that wants a key) is that engine failing,
    not the client's answer: it is never handed on as it came (P2-6)."""
    if status == 404:
        return NOT_FOUND
    if status in (400, 413, 415, 422):
        return BAD_REQUEST
    return DOWN


def classify(exc: BaseException) -> str:
    """What an engine's failure means (`FAULTS`), one reading for both doors.

    * An error that says what it is (`fault`, as the API's refused key does)
      is taken at its word.
    * An HTTP status — an HTTPException from a /v1 forwarder, httpx's
      `HTTPStatusError`, an error carrying `status_code` (Ollama's semantic
      errors) — is read by its number: 404 no such model; 400/413/415/422 a
      bad request; anything else (408, 429, 5xx, 401, 403…) the engine down
      or failing. A deliberate no is only ever an error that says so.
    * Anything else — connection refused, a timeout (builtin or httpx's), out
      of memory, a crash, and a `ValueError` nobody marked (a reshape, a JSON
      decode, a pydantic validation: P2-7) — is this engine down or failing
      at this moment. A bad request or a missing model said on purpose is a
      `core.turn.errors.BadRequest`/`ModelNotFound`: they carry their `fault`.
    """
    own = getattr(exc, "fault", None)
    if own in FAULTS:
        return own
    if isinstance(exc, HTTPException):
        return _fault_of_status(exc.status_code)
    if isinstance(exc, httpx.HTTPStatusError):
        return _fault_of_status(exc.response.status_code)
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return _fault_of_status(status)
    return DOWN


def should_try_next_engine(exc: BaseException, *, in_reserve: bool = False) -> bool:
    """True when the cascade should move on instead of failing the turn.

    The policy, in one place, for both doors (C4.8 N5): an engine down, too
    slow or failing is worth the next one — the footer and the fallback
    headers say which engine answered, so nothing is hidden; a bad request or
    a deliberate no is final for every engine; a model that is not there is
    final for the engine the client asked for (it named a model that does not
    exist) and worth the next one for an engine in reserve (`in_reserve`),
    which was never asked for that name."""
    fault = classify(exc)
    return fault == DOWN or (fault == NOT_FOUND and in_reserve)


def engine_error_to_http(exc: BaseException, engine_name: str, lang: Optional[str] = None) -> Optional[tuple]:
    """``(status, detail)`` of a final error, or None for an engine down or
    failing, which is the cascade's to move past (when nobody is left, the end
    of the cascade tells the first failure, curated: D2/D3).

    The status is what the error carries (an HTTPException's, an engine's 4xx)
    or what it means (404 a missing model, 400 a bad request, 502 a deliberate
    no). The detail is always curated (P2-7, `final_error_text`): an engine's
    own words — an internal URL, a path, a pydantic dump — never reach the
    client, whichever door it came through.
    """
    from core.turn.errors import final_error_text  # deferred: core.turn imports this module

    fault = classify(exc)
    if fault == DOWN:
        return None
    status = getattr(exc, "status_code", None)
    if not isinstance(status, int):
        status = {NOT_FOUND: 404, BAD_REQUEST: 400}.get(fault, 502)
    return status, final_error_text(exc, fault, lang)


def raise_if_terminal(
    exc: BaseException, engine_name: str, *, in_reserve: bool = False, lang: Optional[str] = None,
) -> None:
    """Raise the HTTP answer this error deserves, or return so the caller moves
    on to the next engine.

    Both doors do the same two things with a failed engine — decide, then raise
    the right thing — so both live here rather than being re-expressed at each
    call site. The answer keeps an HTTPException's status and headers; its
    words are the curated ones (`engine_error_to_http`).
    """
    if should_try_next_engine(exc, in_reserve=in_reserve):
        return
    status, detail = engine_error_to_http(exc, engine_name, lang)
    headers = exc.headers if isinstance(exc, HTTPException) else None
    raise HTTPException(status_code=status, detail=detail, headers=headers) from exc
