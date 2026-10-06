"""
------------------------------------
Server Nexe
Location: core/turn/api_cascade.py
Description: What the API door (`POST /v1/chat/completions`) tells the core's
             cascade (`engine_claim.py`), C4.8-c. The loop that `chat.py` used to
             carry (`_dispatch_through_cascade`, gone) is the core's now; what
             is the door's own stays here: the prompt fitted to each engine's window
             (every candidate, the reply reserve is `max_tokens`), the engines
             that cannot see an image left out, the forwarder that starts the
             engine in OpenAI's format and answers with its response, the first
             chunk of a stream read before the response is committed, the
             counters per attempt, and the `(response, engine, fallback_from,
             reason, model)` the turn's steps read. When every engine failed it
             ends as the core's default does, a 503 with the first error curated.

www.jgoy.net · https://server-nexe.org
------------------------------------
"""

import logging
import time
from typing import Any, Optional

from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse

from core.endpoints.chat_engines._common import served_model_of
from core.endpoints.chat_engines._streaming import peek_stream
from core.endpoints.chat_engines.routing import engine_can_see_images
from core.turn.engine_claim import CascadeDoor, Opened, claim_one, live_candidates

logger = logging.getLogger(__name__)


def _chat():
    # Deferred, and by module: core.endpoints.chat imports the turn adapters, and
    # the API's tests patch attributes ON core.endpoints.chat.
    import core.endpoints.chat as chat_mod
    return chat_mod


class ModelNotOnFallback(RuntimeError):
    """An engine in reserve does not have the model the request named: Ollama
    picks its model per request, and the name a client sent for another engine
    is not necessarily one of its tags. A RuntimeError, so the cascade moves on
    to the next engine (D1-z); a 404 would end the turn for every engine."""


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

    def skip(self, index: int, name: str, engine: Any) -> bool:
        """#1081: a FALLBACK whose model says it cannot see is skipped when the
        turn carries an image — it answers with the model it has loaded and
        would answer as if it saw the picture (#1035, the web door's rule)."""
        if index > 0 and self.images and engine_can_see_images(engine) is False:
            logger.warning("Engine %s cannot see the image; trying the next in the cascade", name)
            return True
        return False

    async def prepare(self, index: int, name: str, engine: Any) -> list:
        # #976, per engine: the prompt was fitted to the window of the engine
        # that was RESOLVED, and this loop can hand it to a different one.
        # Falling back from a 32k engine to a 2048 one with the first one's
        # prompt is the very crash the fit guard exists to prevent — and it
        # would only appear on the fallback path, which is the one nobody
        # exercises. Fitting an already-fitted list to a bigger window
        # returns it unchanged.
        chat = _chat()
        return chat._fit_v1_messages_to_window(
            self.messages, chat.get_effective_context_window(name, self.request.app.state), self.body,
        )

    async def read_first(self, index: int, name: str, engine: Any, prepared: list) -> Opened:
        chat = _chat()
        try:
            response = await chat._dispatch_to_engine(
                name, prepared, self.body, self.request, self.request.app.state, self.last_user_msg,
                self.session_id, cancel_event=self.cancel_event, images=self.images,
            )
        except HTTPException as exc:
            # D1-z (provisional): "that model is not on this engine" is reason enough to
            # try the next one, but only for an engine in reserve. The one the client
            # asked for answering 404 is the answer: it named a model that is not there.
            if index > 0 and exc.status_code == 404:
                raise ModelNotOnFallback(f"{name} has no such model: {exc.detail}") from exc
            raise
        if isinstance(response, StreamingResponse):
            # An error before any token reaches the client raises here as a real
            # exception (#1036), which the cascade can still retry.
            await peek_stream(response)
        return Opened(response)

    def observe(self, name: str, ok: bool, started: float) -> None:
        _chat()._record_engine_metrics(name, "success" if ok else "error", started)


async def dispatch_v1(
    body: Any, request: Request, messages: list, last_user_msg: Optional[str], session_id: str,
    engine: str, preferred_fallback: Optional[str], *, cancel_event: Any = None,
    images: Optional[list] = None, resume: bool = False, lang: Optional[str] = None,
) -> tuple:
    """Try the resolved engine, then the rest of the cascade. Returns
    ``(response, engine_that_answered, fallback_from, fallback_reason,
    model_that_answered)``.

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

    Nothing live is a 503, as at the web door (R4, provisional): it used to ask the
    Ollama daemon all the same, registered or not.

    An HTTPException is never retried — that is how the forwarders report a
    backend that is down, and it is the answer, not a crash. What IS retried is
    an engine failing at this moment: a corrupt model, an out-of-memory, a
    driver. This is the ONLY fallback mechanism (#1036, C2.4): the forwarders
    do not fall back on their own.
    """
    # `is True`: a MagicMock body grows a truthy `.resume` on access, and that
    # used to reject every non-resume turn as "continue is not supported".
    candidates = live_candidates(
        body.engine, request.app.state, resume=resume or body.resume is True,
        model_name=getattr(body, "model", None),
    )
    door = ApiDoor(body, request, messages, last_user_msg, session_id,
                   cancel_event=cancel_event, images=images, lang=lang)
    claim = await claim_one(candidates, door, cancel_event=cancel_event)
    if claim.engine_name != engine and not preferred_fallback:
        preferred_fallback = engine
    response = claim.opened.value
    return response, claim.engine_name, preferred_fallback, claim.reason, served_model_of(response)


async def ask_again(
    body: Any, request: Request, messages: list, last_user_msg: Optional[str], session_id: str, engine: str,
) -> Any:
    """The second call of a turn (the re-prompt), to the engine that answered the
    first and to no other (R1, provisional: «the same engine, as the web door»).
    The prompt is fitted to that engine's window and the forwarder answers in
    OpenAI's format; no cascade, no cancel event (the second call has never had
    one at this door). The attempt is counted under its engine, as the cascade
    counted it. A failure is the caller's to take: the re-prompt ends quietly
    and the turn falls back to the neutral stand-in (a stream whose first chunk is
    the engine's own failure sentinel reads as an empty reply: the same stand-in)."""
    chat = _chat()
    state = request.app.state
    fitted = chat._fit_v1_messages_to_window(messages, chat.get_effective_context_window(engine, state), body)
    started = time.time()
    try:
        response = await chat._dispatch_to_engine(engine, fitted, body, request, state, last_user_msg, session_id)
    except Exception:
        chat._record_engine_metrics(engine, "error", started)
        raise
    chat._record_engine_metrics(engine, "success", started)
    return response


__all__ = ["ApiDoor", "ModelNotOnFallback", "ask_again", "dispatch_v1"]
