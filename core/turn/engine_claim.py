"""
------------------------------------
Server Nexe
Location: core/turn/engine_claim.py
Description: The cascade of engines, once (C4.8-b). Which engines a turn may
             try (the live ones, narrowed to those that can resume when the
             turn is a Continue) and the loop that tries them in order until
             one claims the turn. What changes from one door and one wire
             shape to another is not in the loop: a `CascadeDoor` says how to
             start an engine, how to read its first event, and what to do
             with it. The policy of which errors end the turn and which are
             worth another engine stays in `core/endpoints/chat_engines/
             routing.py` (`should_try_next_engine`, `raise_if_terminal`).

www.jgoy.net · https://server-nexe.org
------------------------------------
"""

import contextlib
import logging
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Optional

from fastapi import HTTPException

from core.turn.cancel import TurnCancel, client_gone, first_byte
from core.turn.trace import note_attempt
from core.turn.errors import CANNOT_SEE, NO_OWN_MODEL, UserFacingHTTPException, curated_error_text, no_engine_can_answer

logger = logging.getLogger(__name__)


def _routing():
    """The cascade's routing policy (`core/endpoints/chat_engines/routing.py`),
    looked up at call time. Not imported at the top: the package `core.endpoints`
    imports the whole /v1 route when it is first touched, and that route imports
    `api_cascade`, which needs THIS module's classes — so a fresh interpreter that
    imported this module first would find it half built."""
    from core.endpoints.chat_engines import routing
    return routing


#: What a turn is told when no engine is left to answer it.
NO_ENGINE_DETAIL = "No AI engine available"


class EmptyReply(RuntimeError):
    """An engine answered, and said nothing. A door that wants another engine
    to try raises it from `read_first`; it is not a failure the user is told
    about, only a reason to move on."""


def able_to_continue(candidates: list, model_name: Optional[str]) -> list:
    """On a Continue, only the engines whose prompt can end inside the last
    assistant message. None left is a 400: a Continue that reached another
    engine used to start a new answer and glue it onto the one that was cut."""
    able = [(name, module) for name, module in candidates if _routing().engine_can_continue(module, model_name)]
    if not able:
        raise HTTPException(status_code=400, detail="continue is not supported by the available engines")
    return able


def live_candidates(requested_engine: Optional[str], app_state: Any, *, resume: bool = False,
                    model_name: Optional[str] = None, cloud_ok: bool = False,
                    image: bool = False, lang: Optional[str] = None) -> list:
    """`(name, module)` of every engine worth trying for this turn, best first.

    The live ones in the cascade's order (`resolve_engine_cascade`), narrowed
    to the engines that can resume when the turn is a Continue and to those
    that can answer it at all (`_able_to_answer`): the filters are conditions
    of being a candidate, not copies of the loop's own checks. Nothing live is
    a 503; engines live and none able is a 503 that says why. `cloud_ok` is the
    door saying the cloud gate was passed for this turn; without it the API
    engine is never a candidate. `image`: the turn brings one of its own (an
    image re-attached from the conversation is a help, never a reason, #1144)."""
    cascade = _routing().resolve_engine_cascade(requested_engine, app_state, cloud_ok=cloud_ok)
    # A hosted engine is handed to the turn bound to the turn's model (its
    # window, its sight and the model a compaction asks for are THIS turn's).
    candidates = [(name, _routing().bind_to_model(module, model_name))
                  for name, module in _routing().iter_live_engines(cascade, app_state)]
    if not candidates:
        raise HTTPException(status_code=503, detail=NO_ENGINE_DETAIL)
    if resume:
        candidates = able_to_continue(candidates, model_name)
    return _able_to_answer(candidates, requested_engine, app_state, image=image, lang=lang)


def _able_to_answer(candidates: list, requested_engine: Optional[str], app_state: Any, *,
                    image: bool, lang: Optional[str]) -> list:
    """The candidates that can answer this turn. A fallback with no model of its
    own (Ollama without one said in words, B2/D1-x) is left out, and so is one
    that does not say it sees when the turn brings an image. The engine the
    client asked for is always kept: it decides for itself.

    Decided here, before anything is sent, and not as a door's skip in the
    loop: a door whose response is already out (the web stream) would find
    nobody left to try with no failure to show, and the connection would drop.
    None left is a 503 that says why, at every door, like nothing live."""
    from core.endpoints.chat_engines._common import no_model_of_its_own  # deferred, as `_routing`

    routing = _routing()
    asked = routing.asked_engine(requested_engine, app_state)
    able, why = [], []
    for index, (name, module) in enumerate(candidates):
        if routing.in_reserve(index, name, asked):
            if no_model_of_its_own(name, app_state):
                logger.warning("Engine %s has no model of its own to stand in with; left out", name)
                why.append(NO_OWN_MODEL)
                continue
            if image and routing.engine_can_see_images(module) is not True:
                logger.warning("Engine %s does not say it can see the image; left out", name)
                why.append(CANNOT_SEE)
                continue
        able.append((name, module))
    if not able:
        raise UserFacingHTTPException(status_code=503, detail=no_engine_can_answer(why, lang))
    return able


@dataclass
class Opened:
    """One engine, started and its first event read. `failure` set means the
    first event was a failure the door chose to carry instead of raising (a
    door whose response is already committed shows it as a notice)."""
    value: Any
    failure: Optional[Exception] = None


@dataclass
class Claim:
    """What the cascade settled on.

    `engine` answers, unless `kept`: no engine claimed the turn and this is the
    first one that failed on its first event, kept (with that event already
    read) so the door can write its failure where a raise would cut the
    connection. `passed_over` is every `(engine, error)` that was tried and
    failed before this one, in order."""
    index: int
    engine_name: str
    engine: Any
    opened: Opened
    passed_over: list = field(default_factory=list)
    kept: bool = False

    @property
    def reason(self) -> str:
        """Why this engine and not the first one: it was not live
        (`preferred_unavailable`) or it was live and broke."""
        return "execution_failed" if self.passed_over else "preferred_unavailable"


def fallback_of(claim: "Claim", first_asked: str, already: Optional[str] = None) -> Optional[str]:
    """The engine this turn fell back FROM, if it did (B3/N6): told against the first
    engine the turn ASKED, not against what the `engine` step resolved — on a Continue,
    an engine that cannot resume is left out before the loop, and an engine never
    asked is not one the turn fell back from. `already` (the `engine` step's own,
    when the one named was not live) is kept. One rule for both doors."""
    if claim.engine_name != first_asked and not already:
        return first_asked
    return already


class CascadeDoor:
    """What a door tells the cascade. The defaults are the plainest door: no
    engine skipped, nothing announced, nothing observed. When to stop asking
    is not a door's to say: a client that left is asked nothing more, at
    every door (`_cancelled`, N4)."""

    #: The cancel event of the engine being asked: the cascade hands each engine
    #: one of its own (`TurnCancel.attempt`) and the door starts that engine with it.
    cancel_event: Any = None

    #: The engine the client asked for (`routing.asked_engine`); None when it named none.
    asked: Optional[str] = None

    def in_reserve(self, index: int, name: str) -> bool:
        """Is this engine a fallback — not the one the client asked for (`routing.in_reserve`)?"""
        return _routing().in_reserve(index, name, self.asked)

    #: The turn's reply language: the curated text of a failure is said in it.
    lang: Optional[str] = None

    def skip(self, index: int, name: str, engine: Any) -> bool:
        """True to leave this engine out without it counting as a failure."""
        return False

    async def prepare(self, index: int, name: str, engine: Any) -> Any:
        """Start the engine. Whatever comes back is handed to the next two."""
        raise NotImplementedError

    async def announce(self, index: int, name: str, engine: Any, prepared: Any) -> AsyncIterator[Any]:
        """Anything the door tells its client before it waits on the engine
        (the web's «loading the model» banner). Items go out as they come."""
        return
        yield  # pragma: no cover - makes this an async generator

    async def read_first(self, index: int, name: str, engine: Any, prepared: Any) -> Opened:
        """Wait for the engine's first event (or its whole answer). A raise is
        this engine failing."""
        raise NotImplementedError

    #: The turn's context, when the door has one to say its attempts to (C5 E).
    trace_ctx: Any = None

    def observe(self, name: str, ok: bool, started: float) -> None:
        """One attempt is over: said once on the turn (engine, ok, ms up to its first
        event), and the next `generate` event carries it to every sink. The
        same at every door — no door counts on its own any more."""
        if self.trace_ctx is not None:
            note_attempt(self.trace_ctx, "generate", name, ok, (time.time() - started) * 1000.0)

    def stand_in(self, index: int, name: str, engine: Any, first_error: Exception) -> Optional[Opened]:
        """A door whose response is already out cannot raise a 503 (it would
        cut the connection): it can show the first engine's failure instead,
        as an `Opened` carrying it, the same way a failure on a first event is.
        None (the default) leaves the 503."""
        return None

    def exhausted(self, first_error: Optional[Exception], last_error: Optional[Exception]) -> BaseException:
        """What ends the turn when no engine answered: by default a 503 whose
        text is about the FIRST engine tried, curated (MC-133; D2/D3 — the one
        the user chose is the one worth telling about). An engine that only
        answered nothing, or no engine at all, has nothing to tell."""
        if first_error is None or isinstance(first_error, EmptyReply):
            return HTTPException(status_code=503, detail=NO_ENGINE_DETAIL)
        return HTTPException(status_code=503, detail=curated_error_text(first_error, self.lang))

    async def close(self, prepared: Any) -> None:
        """Let go of an engine that was started and then abandoned."""


@dataclass
class _Verdict:
    kind: str  # "claimed" | "first_failed" | "next" | "keep"
    opened: Optional[Opened] = None
    error: Optional[Exception] = None


async def _try_engine(door: CascadeDoor, index: int, name: str, engine: Any, have_kept: bool):
    """One engine's turn at it: whatever the door announces, then one verdict."""
    started = time.time()
    prepared = None
    try:
        try:
            prepared = await door.prepare(index, name, engine)
            async for item in door.announce(index, name, engine, prepared):
                yield item
            opened = await door.read_first(index, name, engine, prepared)
            prepared = None
        except Exception as exc:
            door.observe(name, False, started)
            logger.warning("%s failed: %s", name, exc)
            logger.debug("Engine error details:", exc_info=True)
            # N5: what the failure means decides, and a model missing from an
            # engine in reserve (never asked for that name) is worth the next one.
            in_reserve = door.in_reserve(index, name)
            if have_kept and not _routing().should_try_next_engine(exc, in_reserve=in_reserve):
                # A notice is already in hand and the response is out: a raise
                # would cut the connection, so the notice is what is shown.
                yield _Verdict("keep", error=exc)
                return
            _routing().raise_if_terminal(exc, name, in_reserve=in_reserve, lang=door.lang)
            yield _Verdict("next", error=exc)
            return
    finally:
        if prepared is not None:
            await door.close(prepared)
    if opened.failure is None:
        door.observe(name, True, started)
        yield _Verdict("claimed", opened=opened)
        return
    door.observe(name, False, started)
    logger.warning("%s failed before its first byte: %s", name, opened.failure)
    logger.debug("Engine error details:", exc_info=opened.failure)
    yield _Verdict("first_failed", opened=opened, error=opened.failure)


def _attempt_event(cancel_event: Any) -> Any:
    """The event the next engine is handed (P2-1): one of its own, linked to the
    turn's, so a deadline an earlier engine used up never reaches it. An event
    that is not the turn's (a plain Event, none) is handed on as it is."""
    return cancel_event.attempt() if isinstance(cancel_event, TurnCancel) else cancel_event


def _cancelled(index: int, cancel_event: Any) -> bool:
    """The client of this turn has left: no other engine is asked for an answer
    nobody will read, at any door (N4). A turn that ran out of time is not a
    client that left: the cascade goes on as it would (`client_gone` reads why
    the event was set). The first engine is always asked."""
    return index > 0 and client_gone(cancel_event)


@dataclass
class _Run:
    """What the loop has learned so far: who failed, and the first failure that
    reached its first event (kept in case nobody claims)."""
    passed_over: list = field(default_factory=list)
    kept: Optional[Claim] = None
    first: Optional[tuple] = None  # (index, name, engine, error) of the first attempt that failed

    def settle(self, verdict: _Verdict, index: int, name: str, engine: Any, *, in_reserve: bool) -> bool:
        """Take one failed attempt into account. True: stop asking engines."""
        self.passed_over.append((name, verdict.error))
        if self.first is None:
            self.first = (index, name, engine, verdict.error)
        if verdict.kind == "keep":
            return True
        if verdict.kind != "first_failed":
            return False
        if self.kept is None:
            self.kept = Claim(index, name, engine, verdict.opened, [], kept=True)
        # final for the policy: no other engine
        return not _routing().should_try_next_engine(verdict.error, in_reserve=in_reserve)


def _stood_in(door: CascadeDoor, run: _Run) -> Claim:
    """Nobody claimed and nobody got as far as a first event: the door shows
    the first failure itself if it can, and the turn is a 503 if it cannot."""
    if run.first is not None:
        index, name, engine, error = run.first
        opened = door.stand_in(index, name, engine, error)
        if opened is not None:
            return Claim(index, name, engine, opened, [], kept=True)
    first_error = run.first[3] if run.first is not None else None
    last_error = run.passed_over[-1][1] if run.passed_over else None
    raise door.exhausted(first_error, last_error) from first_error


async def claim_engine(candidates: list, door: CascadeDoor, *, cancel_event: Any = None):
    """Try the candidates in order; yield what the door announces and, last, the `Claim`.

    A candidate that fails with an error the policy calls final ends the turn
    (`raise_if_terminal`, an HTTP answer; what is final is what the failure
    means, `routing.classify`, N5) — unless the door's response is
    already out and an earlier failure is in hand, and then that failure is
    what is shown. One that fails any other way is passed over for the next.
    When nobody claims: the first failure that reached its first event is kept
    (`Claim.kept`); with none, the door may stand one in for the first failure
    it met, and otherwise it is a 503.

    Limit, kept from before the cascade moved here: a door whose response is
    already out still cannot show a FINAL error from a later engine when no
    failure was in hand yet, nor a cancelled turn that failed nothing — those
    raise, and the connection drops."""
    run = _Run()
    for index, (name, engine) in enumerate(candidates):
        if _cancelled(index, cancel_event):
            break
        if door.skip(index, name, engine):
            logger.warning("Engine %s skipped; trying the next in the cascade", name)
            continue
        logger.info("Trying engine: %s", name)
        engine_event = _attempt_event(cancel_event)
        if engine_event is not cancel_event:
            door.cancel_event = engine_event
        verdict = None
        # aclosing: leaving this loop by an exception (a client that went away)
        # does not close the generator being iterated (PEP 525), and that is
        # the one that lets go of an engine that was started and abandoned.
        async with contextlib.aclosing(_try_engine(door, index, name, engine, run.kept is not None)) as attempt:
            async for item in attempt:
                if isinstance(item, _Verdict):
                    verdict = item
                else:
                    yield item
        if verdict.kind == "claimed":
            # #1165: this engine has started answering (a stream's first event,
            # or a whole JSON answer): its deadline stops watching.
            first_byte(engine_event)
            yield Claim(index, name, engine, verdict.opened, run.passed_over)
            return
        if run.settle(verdict, index, name, engine, in_reserve=door.in_reserve(index, name)):
            break
    if run.kept is None:
        run.kept = _stood_in(door, run)
    yield run.kept


async def claim_one(candidates: list, door: CascadeDoor, *, cancel_event: Any = None) -> Claim:
    """`claim_engine` for a door with nothing to announce along the way."""
    claim = None
    async for item in claim_engine(candidates, door, cancel_event=cancel_event):
        claim = item
    return claim
