"""
------------------------------------
Server Nexe
Location: plugins/web_ui_module/api/engine_doors.py
Description: What the web door tells the core's cascade (`core/turn/
             engine_claim.py`): how one attempt is set up (its model, its image,
             its prompt fitted to the engine's window, the engine started) and
             the two `CascadeDoor`s, one per wire shape. The JSON door reads
             the whole answer; the streaming door reads the engine's first
             event, announces a model that has to load, and carries a failure
             as data because its response is already committed (#1117). C4.8-b:
             the loop that used to be written twice in `turn_adapters.py` (one
             for the JSON reply, one for the stream) is the core's now.

www.jgoy.net · https://server-nexe.org
------------------------------------
"""

from __future__ import annotations

import inspect
import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

from core.turn.engine_claim import CascadeDoor, EmptyReply, Opened
from core.turn.engine_start import start_engine_call
from core.turn.stream import Failed, StreamFlags, close_quietly
from core.turn.validate import parse_top_p
from plugins.web_ui_module.api import engine_call, wire

if TYPE_CHECKING:  # an annotation only: no import-time edge to core.turn.context
    from core.turn.context import TurnContext

logger = logging.getLogger(__name__)


def _model_on_fallback(engine, requested: str) -> str:
    """#1035: the model a fallback engine answers with — the one it has loaded.

    A model name belongs to one engine: an MLX directory is not a .gguf, and
    neither is an Ollama tag. The web doors used to ask the next engine in the
    cascade to load the name picked for another one; its validation raised
    ValueError("not found"), final for the cascade policy, so with a model
    selected in the UI (always) no fallback ever answered. `/v1` already runs
    a fallback with its loaded model; the web doors do the same now. An engine
    with no single loaded model (Ollama picks one per request) gets the
    requested name, as before.
    """
    # Deferred: a plugin must not pull core at import time (layering gate, #471).
    from core.endpoints.chat_engines._common import resolve_loaded_model_name
    return resolve_loaded_model_name(engine, requested)


class _CannotSeeTheImage(RuntimeError):
    """#1035: a fallback whose own model cannot read the turn's image. A
    RuntimeError, so the cascade moves on to the next engine; a ValueError
    would end the turn for every engine."""


def _require_sight(engine, engine_name: str, model_name: str) -> None:
    """A fallback answers with its own model (#1035), and a text model given a
    turn with an image would answer as if it saw it. An engine that says it
    cannot see is skipped; one that does not say (it takes the requested
    model, Ollama) is left as before."""
    from core.endpoints.chat_engines.routing import engine_can_see_images  # deferred, as above
    if engine_can_see_images(engine) is False:
        raise _CannotSeeTheImage(f"{engine_name} runs {model_name}, which cannot see the image")


def _refit_for(engine, system_prompt: str, messages: list) -> list:
    """#976 on a fallback engine: the prompt was fitted to the window of the
    engine that was resolved; another one may hold less."""
    from core.context_window import ask_engine_window
    from core.context_budget import fit_prompt_to_window
    from core.endpoints.chat_sanitization import CHARS_PER_TOKEN_ESTIMATE, DEFAULT_CONTEXT_WINDOW
    window = ask_engine_window(engine) or DEFAULT_CONTEXT_WINDOW
    fitted, _ = fit_prompt_to_window(
        system_prompt, messages, window, reply_budget_tokens=500 // CHARS_PER_TOKEN_ESTIMATE,
    )
    return fitted


async def prepare_call(ctx: TurnContext, ui: dict, index: int, engine_name: str, engine_obj,
                       cancel_event, *, stream: bool):
    """One engine attempt's setup: its model, signature, prompt refit, start.

    The first candidate was switched to the requested model in `engine`; a
    fallback answers with the model it has loaded (#1035), and only if
    that model can see the turn's image when there is one. The model comes
    back last: this attempt's text is parsed, recorded and stored as its."""
    follows = index == 0 and ctx.model_follows_request
    model_name = ui["model_name"] if follows else _model_on_fallback(engine_obj, ui["model_name"])
    image_b64 = ctx.attachments.get("image_b64")
    if image_b64 and ctx.attachments.get("image_reattached"):
        # #1144: a re-attached image is a help, never a reason to pass an
        # engine over — one that cannot see answers from the image's note.
        from core.endpoints.chat_engines.routing import engine_can_see_images  # deferred, as in _require_sight
        if engine_can_see_images(engine_obj) is False:
            image_b64 = None
    elif index > 0 and image_b64:
        _require_sight(engine_obj, engine_name, model_name)
    thinking_enabled = getattr(ctx.session, "thinking_enabled", False)
    sig = inspect.signature(engine_obj.chat)
    messages = ctx.prompt if index == 0 else _refit_for(engine_obj, ctx.system_prompt, ctx.prompt)
    top_p = parse_top_p(ctx.body)
    sampling_kwargs = {"top_p": top_p} if top_p is not None else {}
    chat_result = start_engine_call(
        engine_obj, engine_name, sig, model_name, ctx.system_prompt, messages,
        stream=stream, image_b64=image_b64,
        thinking_enabled=thinking_enabled, cancel_event=cancel_event,
        sampling_kwargs=sampling_kwargs, session_id=ctx.session.id, _continue=ctx.resume,
    )
    return chat_result, sig, messages, thinking_enabled, model_name


@dataclass
class JsonReply:
    """A JSON attempt that answered: its text, and the setup it ran with."""
    text: str
    prepared: tuple
    started: float


class JsonDoor(CascadeDoor):
    """`/ui/chat` without streaming: the whole answer is read before an engine
    counts as having answered, and an empty one is passed over (R3)."""

    def __init__(self, ctx: TurnContext, ui: dict, cancel_event, *, on_capped: Callable[[], None]) -> None:
        self.ctx, self.ui, self.cancel_event, self.on_capped = ctx, ui, cancel_event, on_capped
        self.lang = ctx.lang
        self._started = 0.0

    async def prepare(self, index, name, engine):
        self._started = time.monotonic()
        prepared = await prepare_call(self.ctx, self.ui, index, name, engine, self.cancel_event, stream=False)
        chat_result, sig, messages, thinking_enabled, model_name = prepared
        # C4.5: how this door asks the engine once more, if the turn cleans
        # down to nothing but tags (`postprocess`).
        self.ui["reprompt_call"] = engine_call.reprompt_call_for(
            engine, sig, model_name, messages, thinking_enabled,
        )
        return prepared

    async def read_first(self, index, name, engine, prepared) -> Opened:
        chunks: list[str] = []
        if await engine_call._accumulate_nonstreaming_response(prepared[0], chunks):
            self.on_capped()
        text = "".join(chunks)
        if not text:
            raise EmptyReply(f"{name} answered nothing")
        return Opened(JsonReply(text, prepared, self._started))


async def _no_events():
    """The events of an engine that was never started: none."""
    return
    yield  # pragma: no cover - makes this an async generator


@dataclass
class StreamStart:
    """A streaming attempt that was started and whose first event was read."""
    prepared: tuple
    primed: tuple
    flags: StreamFlags
    started: float


class StreamDoor(CascadeDoor):
    """`/ui/chat` streaming: the first event is read before the engine is given
    the stream, a model that has to load is announced once per turn, and a
    failure on that first event is carried, not raised — the 200 is already
    out (#1117)."""

    stop_when_cancelled = True

    def __init__(self, ctx: TurnContext, ui: dict, cancel_event) -> None:
        self.ctx, self.ui, self.cancel_event = ctx, ui, cancel_event
        self.announced = False

    async def prepare(self, index, name, engine):
        return await prepare_call(self.ctx, self.ui, index, name, engine, self.cancel_event, stream=True)

    async def announce(self, index, name, engine, prepared):
        # After `prepare`: it says which model this attempt runs (a fallback's
        # own, #1035), and that is the one the banner asks about and names.
        # Once per turn: nexe-chat.js keeps a second banner spinning.
        if self.announced:
            return
        async for token in wire._yield_model_loading_check(engine, prepared[-1], name):
            self.announced = True
            yield token

    async def read_first(self, index, name, engine, prepared) -> Opened:
        flags = StreamFlags()
        started = time.time()  # the load and the first token are this call's time
        events, first = await engine_call.claim_engine_start(prepared[0], prepared[-1], flags)
        failure = first.exc if isinstance(first, Failed) else None
        return Opened(StreamStart(prepared, (events, first), flags, started), failure=failure)

    async def close(self, prepared) -> None:
        await close_quietly(prepared[0])

    def stand_in(self, index, name, engine, first_error) -> Opened:
        """D3: the 200 is already out, so a 503 raised here would drop the
        connection with nothing said. When no engine got as far as a first
        event, the FIRST failure is written in the chat as the notice, the way
        a failure on a first event is — its engine, the prompt and the model
        this turn asked for, and nothing started."""
        prepared = (
            None, inspect.signature(engine.chat), self.ctx.prompt,
            getattr(self.ctx.session, "thinking_enabled", False), self.ui["model_name"],
        )
        flags = StreamFlags()
        flags.error = first_error
        start = StreamStart(prepared, (_no_events(), Failed(first_error)), flags, time.time())
        return Opened(start, failure=first_error)


__all__ = ["JsonDoor", "JsonReply", "StreamDoor", "StreamStart", "prepare_call"]
