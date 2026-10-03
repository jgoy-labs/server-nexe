"""#1125: the web door gives the model the time of every user message.

Live 02/10: "hola, nexe quin dia i hora es avui?" — the date was right, and
the model said it had no clock. The time only reached it when a phrase
matched, and "hora es" without its accent did not. Worse for a cache: the
line went on THIS turn's message only and was never rendered again, so the
next prompt did not start with the previous one.

Now every user message carries the time it was sent, in front of its text:
this turn's from the `clock` step, every earlier one from the `timestamp` the
session stores with it. It renders the same every turn. /v1 keeps the phrase
(the client sends its own history); the phrase now reads "hora es" too.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from core.chat_prompt import TIME_INTENT_RE, message_time_line
from core.turn.text.clean import clean_model_text
from core.turn.text.tags import TagStreamFilter

# Any of the three languages: the turn language follows the conversation and
# NEXE_LANG, which another test may have left set (#1121).
LINE = re.compile(r"^\[(Hora del missatge|Hora del mensaje|Message time): (\d{1,2}/\d{1,2} )?\d{2}:\d{2}( \(\w+\))?\]")


# ── the line ────────────────────────────────────────────────────────────────

def test_a_message_from_today_shows_its_time():
    when = datetime.now(timezone.utc)
    line = message_time_line(when.isoformat(), "ca")
    assert line.startswith("[Hora del missatge: " + when.astimezone().strftime("%H:%M"))
    assert "/" not in line


def test_a_message_from_another_day_shows_the_date_too():
    when = datetime.now(timezone.utc) - timedelta(days=1)
    local = when.astimezone()
    assert message_time_line(when.isoformat(), "es").startswith(f"[Hora del mensaje: {local.day}/{local.month} ")


@pytest.mark.parametrize("lang, head", [("en", "[Message time: "), ("fr", "[Message time: "), ("ca-ES", "[Hora del missatge: ")])
def test_the_line_speaks_the_turns_language(lang, head):
    assert message_time_line(datetime.now(timezone.utc), lang).startswith(head)


@pytest.mark.parametrize("bad", [None, "", "ahir", 42])
def test_an_unreadable_time_gives_no_line(bad):
    assert message_time_line(bad, "ca") == ""


# ── /v1's phrase ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("asked", ["hola, nexe quin dia i hora es avui?", "quina hora és?", "hora es ara", "what time is it"])
def test_the_phrase_finds_the_question(asked):
    assert TIME_INTENT_RE.search(asked)


@pytest.mark.parametrize("not_asked", ["la hora establerta", "una hora estranya"])
def test_the_phrase_does_not_find_what_is_not_one(not_asked):
    assert not TIME_INTENT_RE.search(not_asked)


# ── the history ─────────────────────────────────────────────────────────────

def _session():
    from core.sessions.session_manager import ChatSession

    s = ChatSession("s1125")
    s.add_message("user", "hola")
    s.add_message("assistant", "Hola!")
    s.add_message("user", "on visc?")
    return s


def test_every_stored_user_message_carries_its_time():
    s = _session()
    msgs = s.get_context_messages(stamp=lambda m: message_time_line(m.get("timestamp"), "ca"))
    users = [m["content"] for m in msgs if m["role"] == "user"]
    assistants = [m["content"] for m in msgs if m["role"] == "assistant"]
    assert all(LINE.match(u) for u in users)
    assert users[0].endswith("\n\nhola")
    assert assistants == ["Hola!"]


def test_the_history_renders_the_same_every_turn():
    """What a prompt cache keeps from one turn to the next."""
    s = _session()
    stamp = lambda m: message_time_line(m.get("timestamp"), "ca")  # noqa: E731
    assert s.get_context_messages(stamp=stamp) == s.get_context_messages(stamp=stamp)


def test_without_a_stamp_the_history_is_as_stored():
    s = _session()
    assert [m["content"] for m in s.get_context_messages()] == ["hola", "Hola!", "on visc?"]


# ── the web door, end to end ────────────────────────────────────────────────

def _engine(seen):
    class _Engine:
        _node = SimpleNamespace(config=SimpleNamespace(model_path="/models/Qwen3.5-4B-MLX-4bit"))

        async def chat(self, messages, system="", session_id="default", stream_callback=None, **kwargs):
            seen.append(messages)
            stream_callback("ok")
            return {"finish_reason": "stop"}

        async def is_model_loaded(self, model_name=""):
            return True

        def can_continue(self, model_name=None):
            return True

        def can_see_images(self):
            return True

    return _Engine()


async def test_the_web_door_sends_the_time_of_every_message(turn_lab, app_state):
    seen: list = []
    app_state.modules = {"mlx_module": _engine(seen)}
    await turn_lab.ui(streaming=True, session_id="r1125", message="hola")
    await turn_lab.ui(streaming=True, session_id="r1125", message="quin dia i hora es avui?")
    first, second = seen
    assert LINE.match(first[-1]["content"]) and first[-1]["content"].endswith("hola")
    users = [m["content"] for m in second if m["role"] == "user"]
    assert LINE.match(users[-1]) and users[-1].endswith("quin dia i hora es avui?")
    assert any(LINE.match(u) and u.endswith("\n\nhola") for u in users[:-1]), "the earlier message lost its time"


async def test_v1_sends_the_time_of_this_message_too(turn_lab):
    """One rule for both doors. /v1's history is the client's own, and
    carries what the client sends; this turn's message gets its time."""
    ctx = await turn_lab.api(session_id="r1125-v1", message="hola")
    assert LINE.match(ctx.clock_line)
    users = [m["content"] for m in ctx.prompt if m["role"] == "user"]
    assert LINE.match(users[-1]) and users[-1].endswith("hola")


# ── echoed back ─────────────────────────────────────────────────────────────

ECHO = "[Hora del missatge: 17:41 (CEST)]\n\nSón les 17:41."


def test_an_echoed_time_line_is_not_stored():
    assert clean_model_text(ECHO) == "Són les 17:41."


@pytest.mark.parametrize("step", [1, 4, 1000])
def test_an_echoed_time_line_is_not_shown(step):
    f = TagStreamFilter(memory=False, labels=True)
    shown = "".join(f.feed(ECHO[i:i + step]) for i in range(0, len(ECHO), step)) + f.flush()
    assert shown.strip() == "Són les 17:41."


@pytest.mark.parametrize("text", ["A les [10:30] obre.", "[Hora: tres]", "[Message time capsule]"])
def test_other_brackets_with_times_stay(text):
    assert clean_model_text(text) == text
