"""C4.8-b: the cascade of engines, on its own (`core/turn/engine_claim.py`).

The loop used to be written twice in the web door and a third time in /v1; the
part 0 matrix pins what a client sees at each door, and this file pins the loop
itself with doors that do nothing but record what they were asked.
"""
from __future__ import annotations

import threading

import pytest
from fastapi import HTTPException

from core.turn.engine_claim import (
    NO_ENGINE_DETAIL, CascadeDoor, Claim, EmptyReply, Opened, able_to_continue,
    claim_engine, claim_one, live_candidates,
)
from core.endpoints.chat_engines.routing import should_try_next_engine


class _Engine:
    def __init__(self, name, *, can_continue=True):
        self.name = name
        self.asked_model = "unset"
        self._can_continue = can_continue

    def can_continue(self, model_name=None):
        self.asked_model = model_name
        return self._can_continue

    async def chat(self, *a, **k):  # live engines have a chat()
        raise AssertionError("the cascade never calls chat() itself")


class _Door(CascadeDoor):
    """Scripted: `script[name]` is what `prepare` or `read_first` does for that engine."""

    def __init__(self, prepare=None, first=None, skips=(), stop_when_cancelled=False, announce=None):
        self.prepare_errors = prepare or {}
        self.first = first or {}
        self.skips = set(skips)
        self.stop_when_cancelled = stop_when_cancelled
        self.announcements = announce or {}
        self.log = []
        self.observed = []
        self.closed = []

    def skip(self, index, name, engine):
        return name in self.skips

    async def prepare(self, index, name, engine):
        self.log.append(("prepare", name, index))
        err = self.prepare_errors.get(name)
        if err is not None:
            raise err
        return f"prepared-{name}"

    async def announce(self, index, name, engine, prepared):
        for item in self.announcements.get(name, ()):
            yield item

    async def read_first(self, index, name, engine, prepared):
        self.log.append(("first", name))
        what = self.first.get(name, "ok")
        if isinstance(what, Exception):
            raise what
        if what == "ok":
            return Opened(prepared)
        return Opened(prepared, failure=what[1])  # ("fail", exc)

    def observe(self, name, ok, started):
        self.observed.append((name, ok))

    async def close(self, prepared):
        self.closed.append(prepared)


def _engines(*names):
    return [(n, _Engine(n)) for n in names]


async def _all(gen):
    return [x async for x in gen]


# ── candidates ─────────────────────────────────────────────────────────────

class _State:
    def __init__(self, modules):
        self.modules = modules
        self.config = {}


def test_live_candidates_follow_the_cascade_and_name_their_modules(monkeypatch):
    monkeypatch.setenv("NEXE_MODEL_ENGINE", "auto")
    mlx, ollama = _Engine("mlx"), _Engine("ollama")
    mlx._node = object()
    state = _State({"mlx_module": mlx, "ollama_module": ollama})
    got = live_candidates("auto", state)
    assert [(n, m) for n, m in got] == [("mlx", mlx), ("ollama", ollama)]


def test_nothing_live_is_a_503(monkeypatch):
    monkeypatch.setenv("NEXE_MODEL_ENGINE", "auto")
    with pytest.raises(HTTPException) as caught:
        live_candidates("auto", _State({}))
    assert caught.value.status_code == 503 and caught.value.detail == "No AI engine available"


def test_a_continue_keeps_only_the_engines_that_can_resume_and_asks_with_the_model(monkeypatch):
    monkeypatch.setenv("NEXE_MODEL_ENGINE", "auto")
    mlx, ollama = _Engine("mlx", can_continue=False), _Engine("ollama", can_continue=True)
    mlx._node = object()
    state = _State({"mlx_module": mlx, "ollama_module": ollama})
    got = live_candidates("auto", state, resume=True, model_name="qwen")
    assert [n for n, _ in got] == ["ollama"]
    assert ollama.asked_model == "qwen" and mlx.asked_model == "qwen"
    # not a Continue: nobody is asked, nobody is dropped
    mlx.asked_model = ollama.asked_model = "unset"
    assert [n for n, _ in live_candidates("auto", state)] == ["mlx", "ollama"]
    assert mlx.asked_model == "unset" and ollama.asked_model == "unset"


def test_a_continue_no_engine_can_resume_is_a_400():
    with pytest.raises(HTTPException) as caught:
        able_to_continue([("mlx", _Engine("mlx", can_continue=False))], "m")
    assert caught.value.status_code == 400
    assert caught.value.detail == "continue is not supported by the available engines"


# ── the loop ───────────────────────────────────────────────────────────────

async def test_the_first_engine_that_answers_claims_the_turn():
    door = _Door()
    claim = await claim_one(_engines("a", "b"), door)
    assert isinstance(claim, Claim)
    assert (claim.index, claim.engine_name, claim.kept) == (0, "a", False)
    assert claim.opened.value == "prepared-a" and claim.passed_over == []
    assert claim.reason == "preferred_unavailable"
    assert [e for e in door.log if e[0] == "prepare"] == [("prepare", "a", 0)]  # b was never asked
    assert door.observed == [("a", True)]


async def test_an_engine_that_breaks_is_passed_over_and_the_next_answers():
    boom = RuntimeError("worker died")
    door = _Door(prepare={"a": boom})
    claim = await claim_one(_engines("a", "b"), door)
    assert (claim.index, claim.engine_name) == (1, "b")
    assert claim.passed_over == [("a", boom)]
    assert claim.reason == "execution_failed"
    assert door.observed == [("a", False), ("b", True)]


async def test_an_engine_that_breaks_reading_its_first_event_is_passed_over_too():
    door = _Door(first={"a": RuntimeError("oom")})
    claim = await claim_one(_engines("a", "b"), door)
    assert claim.engine_name == "b" and claim.passed_over[0][0] == "a"


@pytest.mark.parametrize("error, status", [
    (ValueError("bad request"), 400),
    (ValueError("model X not found"), 404),
    (ConnectionError("refused"), 503),
    (TimeoutError("slow"), 504),
])
async def test_a_final_error_ends_the_turn_and_no_other_engine_is_asked(error, status):
    door = _Door(prepare={"a": error})
    with pytest.raises(HTTPException) as caught:
        await claim_one(_engines("a", "b"), door)
    assert caught.value.status_code == status
    assert [e[1] for e in door.log if e[0] == "prepare"] == ["a"]
    assert door.observed == [("a", False)]


async def test_an_http_answer_from_an_engine_reaches_the_client_as_written():
    door = _Door(prepare={"a": HTTPException(status_code=502, detail="down")})
    with pytest.raises(HTTPException) as caught:
        await claim_one(_engines("a", "b"), door)
    assert (caught.value.status_code, caught.value.detail) == (502, "down")
    assert [e[1] for e in door.log if e[0] == "prepare"] == ["a"]


async def test_nobody_answering_is_a_503_that_tells_the_first_error_curated():
    """D2/D3: the text is about the FIRST engine tried (the one the user chose),
    in the turn's language, and never the exception's own words."""
    first = RuntimeError("/Users/x/secret-path: boom")
    last = RuntimeError("[METAL] Insufficient Memory")  # an OOM at the end must not take over
    door = _Door(prepare={"a": first, "b": last})
    door.lang = "en"
    with pytest.raises(HTTPException) as caught:
        await claim_one(_engines("a", "b"), door)
    assert caught.value.status_code == 503
    assert caught.value.detail == "An error occurred while generating the response. Please try again."


async def test_the_first_error_in_the_503_is_said_in_the_turns_language_and_ca_by_default():
    door = _Door(prepare={"a": RuntimeError("x")})
    with pytest.raises(HTTPException) as caught:
        await claim_one(_engines("a"), door)
    assert caught.value.detail == "S'ha produït un error en generar la resposta. Torna-ho a provar."
    door = _Door(prepare={"a": RuntimeError("x")})
    door.lang = "es"
    with pytest.raises(HTTPException) as caught:
        await claim_one(_engines("a"), door)
    assert caught.value.detail == "Se ha producido un error al generar la respuesta. Inténtalo de nuevo."


async def test_a_first_engine_that_ran_out_of_memory_says_so_in_the_503():
    door = _Door(prepare={"a": RuntimeError("OutOfMemory"), "b": RuntimeError("x")})
    door.lang = "en"
    with pytest.raises(HTTPException) as caught:
        await claim_one(_engines("a", "b"), door)
    assert caught.value.detail.startswith("Not enough memory.")


async def test_a_first_engine_that_answered_nothing_has_no_error_to_tell():
    door = _Door(first={"a": EmptyReply("nothing")}, prepare={"b": RuntimeError("x")})
    with pytest.raises(HTTPException) as caught:
        await claim_one(_engines("a", "b"), door)
    assert caught.value.status_code == 503 and caught.value.detail == "No AI engine available"


async def test_no_candidates_is_a_503():
    with pytest.raises(HTTPException) as caught:
        await claim_one([], _Door())
    assert caught.value.status_code == 503 and caught.value.detail == "No AI engine available"


async def test_an_empty_reply_is_a_reason_to_move_on_not_a_final_error():
    assert should_try_next_engine(EmptyReply("nothing"))
    door = _Door(first={"a": EmptyReply("a answered nothing")})
    claim = await claim_one(_engines("a", "b"), door)
    assert claim.engine_name == "b"


async def test_a_skipped_engine_is_not_asked_and_is_not_a_failure():
    door = _Door(skips={"a"})
    claim = await claim_one(_engines("a", "b"), door)
    assert claim.engine_name == "b" and claim.passed_over == []
    assert claim.reason == "preferred_unavailable"
    assert door.observed == [("b", True)]
    assert all(e[1] != "a" for e in door.log)


async def test_a_cancelled_turn_asks_no_other_engine_when_the_door_says_so():
    event = threading.Event()
    door = _Door(prepare={"a": RuntimeError("x")}, stop_when_cancelled=True)
    event.set()
    with pytest.raises(HTTPException) as caught:   # engine 0 is always asked; nobody is left
        await claim_one(_engines("a", "b"), door, cancel_event=event)
    assert caught.value.status_code == 503
    assert [e[1] for e in door.log if e[0] == "prepare"] == ["a"]


async def test_a_cancelled_turn_still_asks_the_first_engine():
    event = threading.Event()
    event.set()
    door = _Door(stop_when_cancelled=True)
    claim = await claim_one(_engines("a"), door, cancel_event=event)
    assert claim.engine_name == "a"


async def test_a_door_that_does_not_stop_keeps_asking_a_cancelled_turn():
    event = threading.Event()
    event.set()
    door = _Door(prepare={"a": RuntimeError("x")}, stop_when_cancelled=False)
    claim = await claim_one(_engines("a", "b"), door, cancel_event=event)
    assert claim.engine_name == "b"


async def test_without_an_event_a_stopping_door_just_goes_on():
    door = _Door(prepare={"a": RuntimeError("x")}, stop_when_cancelled=True)
    claim = await claim_one(_engines("a", "b"), door, cancel_event=None)
    assert claim.engine_name == "b"


# ── announcements and a door that carries a failure ─────────────────────────

async def test_what_the_door_announces_comes_out_before_the_claim_in_order():
    door = _Door(announce={"a": ["loading-a"]})
    items = await _all(claim_engine(_engines("a"), door))
    assert items[0] == "loading-a" and isinstance(items[-1], Claim) and len(items) == 2


async def test_closing_the_cascade_while_it_announces_lets_go_of_the_started_engine():
    door = _Door(announce={"a": ["loading-a", "more"]})
    gen = claim_engine(_engines("a"), door)
    assert await gen.__anext__() == "loading-a"
    await gen.aclose()
    assert door.closed == ["prepared-a"]


async def test_an_engine_whose_first_event_was_read_is_not_closed_by_the_cascade():
    door = _Door()
    await claim_one(_engines("a"), door)
    assert door.closed == []


async def test_an_engine_that_failed_to_start_is_never_closed_because_nothing_was_started():
    door = _Door(prepare={"a": RuntimeError("x")})
    with pytest.raises(HTTPException):
        await claim_one(_engines("a"), door)
    assert door.closed == []


async def test_a_failure_on_the_first_event_is_carried_and_the_next_engine_still_tried():
    boom = RuntimeError("reset")
    door = _Door(first={"a": ("fail", boom)})
    claim = await claim_one(_engines("a", "b"), door)
    assert claim.engine_name == "b" and not claim.kept and claim.passed_over == [("a", boom)]
    assert door.observed == [("a", False), ("b", True)]


async def test_when_nobody_claims_the_FIRST_failure_is_kept_not_the_last():
    first, second = RuntimeError("first"), RuntimeError("second")
    door = _Door(first={"a": ("fail", first), "b": ("fail", second)})
    claim = await claim_one(_engines("a", "b"), door)
    assert claim.kept is True and claim.engine_name == "a" and claim.index == 0
    assert claim.opened.failure is first and claim.passed_over == []
    assert [e[1] for e in door.log if e[0] == "first"] == ["a", "b"]  # b was asked all the same


async def test_a_final_failure_on_the_first_event_stops_the_cascade_and_is_kept():
    final = ValueError("bad request")
    door = _Door(first={"a": ("fail", final), "b": "ok"})
    claim = await claim_one(_engines("a", "b"), door)
    assert claim.kept and claim.engine_name == "a" and claim.opened.failure is final
    assert all(e[1] != "b" for e in door.log)


async def test_with_a_notice_in_hand_a_later_final_start_error_keeps_the_notice():
    first = RuntimeError("down")
    door = _Door(first={"a": ("fail", first)}, prepare={"b": ValueError("cannot take it")})
    claim = await claim_one(_engines("a", "b", "c"), door)
    assert claim.kept and claim.engine_name == "a" and claim.opened.failure is first
    assert all(e[1] != "c" for e in door.log)


async def test_with_a_notice_in_hand_a_later_retryable_start_error_goes_on():
    first = RuntimeError("down")
    door = _Door(first={"a": ("fail", first)}, prepare={"b": RuntimeError("also down")})
    claim = await claim_one(_engines("a", "b", "c"), door)
    assert claim.engine_name == "c" and not claim.kept


async def test_without_a_notice_in_hand_a_final_start_error_is_the_http_answer():
    door = _Door(prepare={"a": ValueError("cannot take it")})
    with pytest.raises(HTTPException) as caught:
        await claim_one(_engines("a"), door)
    assert caught.value.status_code == 400


async def test_claim_one_returns_the_claim_and_drops_the_announcements():
    door = _Door(announce={"a": ["x", "y"]})
    claim = await claim_one(_engines("a"), door)
    assert isinstance(claim, Claim)


async def test_the_default_door_asks_nothing_of_anyone():
    door = CascadeDoor()
    assert door.skip(0, "a", None) is False and door.stop_when_cancelled is False
    door.observe("a", True, 0.0)
    assert await door.close("anything") is None   # an abandoned engine, and nothing to do about it
    assert [x async for x in door.announce(0, "a", None, "p")] == []
    assert door.stand_in(0, "a", None, RuntimeError("x")) is None
    assert isinstance(door.exhausted(None, None), HTTPException)
    assert door.lang is None


# ── the web door's two doors (what each one tells the cascade) ───────────────

async def test_the_web_json_door_records_how_long_the_answering_attempt_took(turn_lab):
    ctx = await turn_lab.ui(streaming=False, session_id="c48b-ms-json")
    calls = ctx.usage["llm"]["calls"]
    assert [c["step"] for c in calls] == ["generate"]
    assert 0 <= calls[0]["ms"] < 5000  # a clock reading of 0.0 would make it the machine's uptime


async def test_the_web_stream_door_records_how_long_the_answering_attempt_took(turn_lab):
    ctx = await turn_lab.ui(streaming=True, session_id="c48b-ms-stream")
    generate = [c for c in ctx.usage["llm"]["calls"] if c["step"] == "generate"]
    assert len(generate) == 1 and 0 <= generate[0]["ms"] < 5000


@pytest.mark.parametrize("streaming", [False, True])
async def test_top_p_reaches_the_engine_at_the_web_door(turn_lab, fake_engine, streaming):
    seen = []
    original = type(fake_engine).chat

    async def chat(messages, system=None, stream_callback=None, session_id=None, images=None,
                   thinking_enabled=False, **kwargs):
        seen.append(kwargs)
        async for piece in original(fake_engine, messages, system):
            yield piece

    fake_engine.chat = chat
    await turn_lab.ui(streaming=streaming, session_id=f"c48b-top-p-{streaming}", body_extra={"top_p": 0.5})
    assert seen == [{"top_p": 0.5}]
    seen.clear()
    await turn_lab.ui(streaming=streaming, session_id=f"c48b-no-top-p-{streaming}")
    assert seen == [{}]


async def test_the_stream_door_lets_go_of_an_engine_it_started_and_abandoned():
    from plugins.web_ui_module.api.engine_doors import StreamDoor

    closed = []

    async def started():
        try:
            yield "never read"
        finally:
            closed.append(True)

    agen = started()
    await agen.__anext__()
    door = StreamDoor(ctx=None, ui={}, cancel_event=None)
    await door.close((agen, None, [], False, "m"))
    assert closed == [True]


async def test_the_json_door_reports_a_capped_reply(turn_lab, monkeypatch):
    from core.endpoints.chat_engines import _streaming

    monkeypatch.setattr(_streaming, "MAX_STREAM_BYTES", 8)
    ctx = await turn_lab.ui(streaming=False, session_id="c48b-capped")
    assert ctx.partial is True and ctx.error["message"] == "stream_cap_exceeded"


# ── the curated words (moved to the core: a JSON reply says what the chat says) ──

def test_curated_text_never_carries_the_exceptions_own_words():
    from core.turn.errors import curated_error_text

    secret = RuntimeError("/Users/someone/models/secret.gguf: boom")
    for lang in ("ca", "es", "en"):
        text = curated_error_text(secret, lang)
        assert "secret" not in text and "boom" not in text


def test_curated_text_by_language():
    from core.turn.errors import curated_error_text

    plain = RuntimeError("x")
    assert curated_error_text(plain, "en") == "An error occurred while generating the response. Please try again."
    assert curated_error_text(plain, "es") == "Se ha producido un error al generar la respuesta. Inténtalo de nuevo."
    assert curated_error_text(plain, "ca") == "S'ha produït un error en generar la resposta. Torna-ho a provar."
    assert curated_error_text(plain, None) == curated_error_text(plain, "ca")      # Catalan is the default
    assert curated_error_text(plain, "de") == curated_error_text(plain, "en")      # an unknown language gets English
    assert curated_error_text(plain, "es-ES") == curated_error_text(plain, "es")   # a region is ignored


def test_curated_text_for_an_out_of_memory_error_names_the_way_out():
    from core.turn.errors import curated_error_text

    assert curated_error_text(RuntimeError("OutOfMemory while allocating"), "en") == (
        "Not enough memory. Close other applications to free up memory and try again."
    )
    mlx = curated_error_text(RuntimeError("MLX: Insufficient Memory to load"), "en")
    assert mlx.startswith("Not enough memory to load the model with MLX. Switch the engine to Ollama")


def test_an_exception_without_a_message_is_judged_by_its_repr():
    from core.turn.errors import curated_error_text

    class OutOfMemory(Exception):
        pass

    # str() is empty, repr() is "OutOfMemory()": that is what names the failure
    assert curated_error_text(OutOfMemory(), "en").startswith("Not enough memory")


async def test_a_door_that_stands_in_shows_the_first_failure_instead_of_a_503():
    """D3: no engine got as far as a first event. A door whose response is out
    cannot raise (it would cut the connection): it stands in a failure to show."""
    first, second = RuntimeError("first"), RuntimeError("second")
    seen = []

    class _Showing(_Door):
        def stand_in(self, index, name, engine, first_error):
            seen.append((index, name, first_error))
            return Opened("stand-in", failure=first_error)

    door = _Showing(prepare={"a": first, "b": second})
    claim = await claim_one(_engines("a", "b"), door)
    assert claim.kept is True and claim.opened.value == "stand-in" and claim.opened.failure is first
    assert (claim.index, claim.engine_name, claim.passed_over) == (0, "a", [])
    assert seen == [(0, "a", first)]  # asked once, about the FIRST failure


async def test_the_stand_in_is_about_the_first_engine_that_failed_not_the_first_candidate():
    boom = RuntimeError("b broke")

    class _Showing(_Door):
        def stand_in(self, index, name, engine, first_error):
            return Opened("stand-in", failure=first_error)

    door = _Showing(skips={"a"}, prepare={"b": boom})
    claim = await claim_one(_engines("a", "b"), door)
    assert (claim.index, claim.engine_name) == (1, "b") and claim.opened.failure is boom


async def test_a_door_that_declines_to_stand_in_gets_the_503():
    class _Declining(_Door):
        def stand_in(self, index, name, engine, first_error):
            return None

    with pytest.raises(HTTPException) as caught:
        await claim_one(_engines("a"), _Declining(prepare={"a": RuntimeError("x")}))
    assert caught.value.status_code == 503


async def test_with_no_failure_to_show_not_even_a_standing_in_door_has_anything_to_say():
    class _Showing(_Door):
        def stand_in(self, index, name, engine, first_error):
            raise AssertionError("there is no failure to stand in for")

    with pytest.raises(HTTPException) as caught:
        await claim_one(_engines("a"), _Showing(skips={"a"}))
    assert caught.value.status_code == 503 and caught.value.detail == "No AI engine available"


async def test_the_stream_door_stands_in_the_first_failure_as_data():
    import inspect

    from core.turn.stream import Failed
    from plugins.web_ui_module.api.engine_doors import StreamDoor

    class _Session:
        thinking_enabled = True

    class _Ctx:
        prompt = [{"role": "user", "content": "hola"}]
        session = _Session()

    engine = _Engine("ollama")
    boom = RuntimeError("connection reset")
    door = StreamDoor(ctx=_Ctx(), ui={"model_name": "qwen"}, cancel_event=None)
    opened = door.stand_in(0, "ollama", engine, boom)
    start = opened.value
    assert opened.failure is boom
    chat_result, sig, messages, thinking, model = start.prepared
    assert chat_result is None and sig == inspect.signature(engine.chat)
    assert messages == _Ctx.prompt and thinking is True and model == "qwen"
    events, first = start.primed
    assert isinstance(first, Failed) and first.exc is boom
    assert [e async for e in events] == []          # nothing more to read
    assert start.flags.error is boom


# ── D1: a door says whether the request's model is the first engine's ─────────

@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("follows, switched_to, model_after", [(True, ["qwen"], "qwen"), (False, [], "Loaded-Model")])
async def test_the_model_of_the_first_engine_follows_the_request_only_where_the_door_says_so(
        turn_lab, fake_engine, monkeypatch, streaming, follows, switched_to, model_after):
    """D1 (provisional): the web door's picker names the model and the first
    engine is switched to it; a door that says no gets the model the engine has
    loaded, as a fallback always does (#1035)."""
    from types import SimpleNamespace

    from plugins.web_ui_module.api import turn_adapters

    fake_engine._node = SimpleNamespace(config=SimpleNamespace(model_path="/models/Loaded-Model"))
    switched = []

    async def spy(engine, engine_name, model_name):
        switched.append(model_name)

    monkeypatch.setattr(turn_adapters, "_switch_model", spy)
    ctx = await turn_lab.ui(
        streaming=streaming, session_id=f"c48b-d1-{streaming}-{follows}", body_extra={"model": "qwen"},
        model_follows_request=follows,
    )
    assert switched == switched_to
    assert ctx.usage["ui"]["model_name"] == model_after


def test_the_api_door_declares_that_the_request_does_not_pick_the_model():
    """`/v1` builds its turn with the flag off, the web route says it is on. Read
    off the syntax tree, not the text: a comment that spells the flag is not a
    declaration. The two constructors are the only places it is said."""
    import ast
    import inspect
    import textwrap

    import core.endpoints.chat as chat_mod
    import plugins.web_ui_module.api.routes_chat as routes_chat
    from core.turn.context import TurnContext

    def declared(function) -> list:
        tree = ast.parse(textwrap.dedent(inspect.getsource(function)))
        found = []
        for call in (n for n in ast.walk(tree) if isinstance(n, ast.Call)):
            if getattr(call.func, "id", None) == "TurnContext":
                found += [kw.value.value for kw in call.keywords
                          if kw.arg == "model_follows_request" and isinstance(kw.value, ast.Constant)]
        return found

    assert TurnContext(turn_id="t").model_follows_request is True
    assert declared(chat_mod.chat_completions) == [False]
    assert declared(routes_chat.register_chat_routes) == [True]


# ── closing what was started (the paths only a cancel reaches) ───────────────

async def test_an_engine_whose_first_read_fails_is_closed_by_the_cascade():
    """`read_first` raises: the engine `prepare` started is abandoned, and the
    cascade is who lets go of it."""
    door = _Door(first={"a": RuntimeError("worker died")})
    claim = await claim_one(_engines("a", "b"), door)
    assert claim.engine_name == "b"
    assert door.closed == ["prepared-a"]


async def test_an_engine_is_closed_when_the_turn_is_cancelled_while_its_first_read_waits():
    import asyncio

    release = asyncio.Event()

    class _Waiting(_Door):
        async def read_first(self, index, name, engine, prepared):
            self.log.append(("first", name))
            await release.wait()
            return Opened(prepared)

    door = _Waiting()
    task = asyncio.ensure_future(claim_one(_engines("a"), door))
    for _ in range(50):
        if ("first", "a") in door.log:
            break
        await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert door.closed == ["prepared-a"]


async def test_a_door_that_ends_the_turn_itself_is_told_the_first_and_the_last_error():
    first, last = RuntimeError("first"), RuntimeError("last")
    told = []

    class _Own(_Door):
        def exhausted(self, first_error, last_error):
            told.append((first_error, last_error))
            return ValueError("the door's own end")

    door = _Own(prepare={"a": first, "b": RuntimeError("middle"), "c": last})
    with pytest.raises(ValueError, match="the door's own end"):
        await claim_one(_engines("a", "b", "c"), door)
    assert told == [(first, last)]


async def test_a_turn_that_met_no_failure_tells_the_door_so():
    told = []

    class _Own(_Door):
        def exhausted(self, first_error, last_error):
            told.append((first_error, last_error))
            return HTTPException(status_code=503, detail="x")

    with pytest.raises(HTTPException):
        await claim_one(_engines("a"), _Own(skips={"a"}))
    assert told == [(None, None)]


def test_the_core_cascade_can_be_imported_before_anything_else_in_a_fresh_interpreter():
    """The routing policy is looked up at call time: `core.endpoints` imports the whole
    /v1 route when first touched, and that route imports the API door's cascade, which
    needs this module's classes — imported first, this module used to be found half built."""
    import subprocess
    import sys

    for module in ("core.turn.engine_claim", "core.turn.api_cascade"):
        done = subprocess.run([sys.executable, "-c", f"import {module}"], capture_output=True, text=True, timeout=120)
        assert done.returncode == 0, done.stderr[-400:]


async def test_the_503_of_a_cascade_that_found_nobody_keeps_the_first_error_as_its_cause():
    first = RuntimeError("the first one")
    with pytest.raises(HTTPException) as caught:
        await claim_one(_engines("a", "b"), _Door(prepare={"a": first, "b": RuntimeError("second")}))
    assert caught.value.__cause__ is first
