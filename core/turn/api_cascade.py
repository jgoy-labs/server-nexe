"""
------------------------------------
Server Nexe
Location: core/turn/api_cascade.py
Description: What the API door (`POST /v1/chat/completions`) tells the core's
             cascade (`engine_claim.py`), C4.8-c. The loop that `chat.py` used to
             carry (`_dispatch_through_cascade`, gone) is the core's now; what
             is the door's own stays here: the prompt fitted to each engine's window
             (every candidate, the reply reserve of `reply_reserve_tokens`), the engines
             that cannot see an image left out, the forwarder that starts the
             engine in OpenAI's format and answers with its response, the first
             chunk of a stream read before the response is committed, the
             counters per attempt, and the `(response, engine, fallback_from,
             reason, model)` the turn's steps read. When every engine failed it
             ends as the core's default does, a 503 with the first error curated.

www.jgoy.net · https://server-nexe.org
------------------------------------
"""

import copy
import logging
from typing import Any, Optional

from fastapi import Request
from fastapi.responses import StreamingResponse

from core.endpoints.chat_engines._common import model_in_reserve, served_model_of
from core.endpoints.chat_engines._streaming import peek_stream
from core.endpoints.chat_engines.routing import asked_engine, cloud_request_ok, engine_takes_model
from core.turn.engine_claim import CascadeDoor, Opened, claim_one, fallback_of, live_candidates

logger = logging.getLogger(__name__)


def _chat():
    # Deferred, and by module: core.endpoints.chat imports the turn adapters, and
    # the API's tests patch attributes ON core.endpoints.chat.
    import core.endpoints.chat as chat_mod
    return chat_mod


def _naming(body: Any, model: Optional[str]) -> Any:
    """The same request, naming another model. A copy: the client's body is the
    turn's, and the engine in front (or a re-prompt) still reads its model."""
    if hasattr(type(body), "model_copy"):
        return body.model_copy(update={"model": model})
    other = copy.copy(body)
    other.model = model
    return other


class ApiDoor(CascadeDoor):
    """`/v1`: each attempt is a forwarder call (`_dispatch_to_engine`) with the
    prompt fitted to that engine's window; a stream is read up to its first
    chunk before the engine counts as having answered."""

    def __init__(self, body: Any, request: Request, messages: list, last_user_msg: Optional[str],
                 session_id: str, *, cancel_event: Any, images: Optional[list],
                 lang: Optional[str] = None) -> None:
        self.lang = lang
        self.body, self.request, self.messages = body, request, messages
        self.last_user_msg, self.session_id = last_user_msg, session_id
        self.cancel_event, self.images = cancel_event, images
        self.asked = asked_engine(getattr(body, "engine", None), request.app.state)

    def _body_for(self, index: int, name: str, engine: Any) -> Any:
        """B2/D1-x: an engine in reserve answers with its own model. One that
        takes the model per request (Ollama) is handed a body naming its own
        default, not the name the client picked for the engine in front; the
        others run what they have loaded whatever the body says."""
        if not self.in_reserve(index, name) or not engine_takes_model(engine):
            return self.body
        own = model_in_reserve(name, engine, getattr(self.body, "model", None), self.request.app.state)
        return _naming(self.body, own)

    async def prepare(self, index: int, name: str, engine: Any) -> list:
        # #976, per engine: the prompt was fitted to the window of the engine
        # that was RESOLVED, and this loop can hand it to a different one.
        # Falling back from a 32k engine to a 2048 one with the first one's
        # prompt is the very crash the fit guard exists to prevent — and it
        # would only appear on the fallback path, which is the one nobody
        # exercises. Fitting an already-fitted list to a bigger window
        # returns it unchanged.
        chat = _chat()
        body = self._body_for(index, name, engine)
        return chat._fit_v1_messages_to_window(
            self.messages,
            chat.get_effective_context_window(name, self.request.app.state, getattr(body, "model", None)),
            body,
        )

    async def read_first(self, index: int, name: str, engine: Any, prepared: list) -> Opened:
        chat = _chat()
        # A 404 from an engine in reserve moves on to the next one, and from the
        # engine the client asked for it is the answer (D1-z): the policy's call
        # (`routing.should_try_next_engine`, N5), not this door's.
        response = await chat._dispatch_to_engine(
            name, prepared, self._body_for(index, name, engine), self.request, self.request.app.state,
            self.last_user_msg, self.session_id, cancel_event=self.cancel_event, images=self.images,
        )
        if isinstance(response, StreamingResponse):
            # An error before any token reaches the client raises here as a real
            # exception (#1036), which the cascade can still retry.
            await peek_stream(response)
        return Opened(response)


async def dispatch_v1(
    body: Any, request: Request, messages: list, last_user_msg: Optional[str], session_id: str,
    engine: str, preferred_fallback: Optional[str], *, cancel_event: Any = None,
    images: Optional[list] = None, resume: bool = False, lang: Optional[str] = None,
    trace_ctx: Any = None,
) -> tuple:
    """Try the resolved engine, then the rest of the cascade. Returns
    ``(response, engine_that_answered, fallback_from, fallback_reason,
    model_that_answered)``. `engine` is what the `engine` step resolved; the
    switch (`fallback_from`) is reported against the first engine the loop
    asked, which a Continue may have narrowed to another (B3/N6).

    The last element is #1054: the engine's NAME is not the model's, and the
    turn's LLM counter had no way to reach the second one. Read off the
    response the forwarder just built (`served_model_of`), so no forwarder
    signature changes and a patched double that returns a bare dict keeps
    working.

    F-D block 5. This door used to dispatch exactly once: whatever the single
    engine raised became the client's error, while /ui/chat quietly walked down
    its list and answered. The list and the policy are the same at both doors
    now (`engine_claim.claim_engine`), and the response headers name the engine
    that actually answered rather than the one that was picked.

    Nothing live is a 503, as at the web door (R4): it used to ask the
    Ollama daemon all the same, registered or not.

    What is worth the next engine is what the failure MEANS (N5,
    `routing.classify`), the same at the web door: a backend down, too slow
    or failing — the forwarders' 5xx included — moves on; a bad request ends
    the turn; a missing model ends it only for the engine the client asked
    for. This is the ONLY fallback mechanism (#1036, C2.4): the forwarders do
    not fall back on their own.
    """
    # `is True`: a MagicMock body grows a truthy `.resume` on access, and that
    # used to reject every non-resume turn as "continue is not supported".
    candidates = live_candidates(
        body.engine, request.app.state, resume=resume or body.resume is True,
        model_name=getattr(body, "model", None),
        # The API is a candidate only when the body asked for it AND the cloud
        # gate passes: asked again here, on the body, by the step that opens the way.
        cloud_ok=cloud_request_ok(body), image=bool(images), lang=lang,
    )
    door = ApiDoor(body, request, messages, last_user_msg, session_id,
                   cancel_event=cancel_event, images=images, lang=lang)
    door.trace_ctx = trace_ctx
    claim = await claim_one(candidates, door, cancel_event=cancel_event)
    preferred_fallback = fallback_of(claim, candidates[0][0], preferred_fallback)
    response = claim.opened.value
    return response, claim.engine_name, preferred_fallback, claim.reason, served_model_of(response)


async def ask_again(
    body: Any, request: Request, messages: list, last_user_msg: Optional[str], session_id: str, engine: str,
) -> Any:
    """The second call of a turn (the re-prompt), to the engine that answered the
    first and to no other (R1: the same engine, as at the web door).
    The prompt is fitted to that engine's window and the forwarder answers in
    OpenAI's format; no cascade, no cancel event (the second call has never had
    one at this door). The attempt is counted under its engine, as the cascade
    counted it. A failure is the caller's to take: the re-prompt ends quietly
    and the turn falls back to the neutral stand-in (a stream whose first chunk is
    the engine's own failure sentinel reads as an empty reply: the same stand-in)."""
    chat = _chat()
    state = request.app.state
    window = chat.get_effective_context_window(engine, state, getattr(body, "model", None))
    fitted = chat._fit_v1_messages_to_window(messages, window, body)
    return await chat._dispatch_to_engine(engine, fitted, body, request, state, last_user_msg, session_id)


__all__ = ["ApiDoor", "ask_again", "dispatch_v1"]
