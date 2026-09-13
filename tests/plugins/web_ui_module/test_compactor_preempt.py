"""C2.2 (ADR-007 §6): compaction moves to the post-commit queue, and gains
two things it never needed inline — a slice it can trust, and a way to be
told to stand down.

`apply_compaction` used to always keep "the last COMPACT_KEEP messages",
measured at APPLY time. That was safe when compaction ran inline, before
generation, with nothing else touching the session in between. Queued and
run in the background, a user turn can append a new message while the LLM
summarisation is in flight — "the last COMPACT_KEEP at apply time" is a
different, newer slice than the one the summary actually covers, and the
gap between them would be silently dropped (neither in the summary nor kept
verbatim). `compacted_count` pins the slice to the one measured BEFORE the
(slow) LLM call.

`cancel_event` is the engine gate's preemption signal (core/turn/gate.py):
a waiting user turn sets it, cooperatively, on any background holder. A
preempted compaction must not apply — the summary was already paid for, but
applying it would still race the same way (the session the gate freed for
the user turn may have moved on by the time the background job resumes).

Mutation checks (exercised by hand before merging, see the diari):
  * reverting `apply_compaction` to always use `[-COMPACT_KEEP:]` turns
    `test_apply_compaction_keeps_exactly_what_was_not_summarised` red;
  * dropping the `cancel_event.is_set()` check in `compact_session` turns
    `test_preempted_compaction_does_not_apply` red.
"""
from __future__ import annotations

import threading

import pytest

from core.sessions.session_manager import ChatSession
from core.sessions.compactor import compact_session


def _session_with(n_user_turns: int, sid: str = "sess-compact-1") -> ChatSession:
    """Long enough messages to cross needs_compaction's 45%-of-window
    threshold against the DEFAULT_CONTEXT_WINDOW (8192 tokens) our fake
    engine reports nothing about (ask_engine_window returns None for it)."""
    session = ChatSession(session_id=sid)
    for i in range(n_user_turns):
        session.add_message("user", f"missatge d'usuari numero {i} " * 40)
        session.add_message("assistant", f"resposta de l'assistent numero {i} " * 40)
    return session


class _FixedWindowEngine:
    """`_call_engine` dispatch picks the non-Ollama branch (system= kwarg) for
    anything whose class name is not ollama-shaped — good enough here."""

    def __init__(self, summary: str = "Resum de la conversa.") -> None:
        self._summary = summary

    async def chat(self, messages, system=None, **_):
        return {"message": {"content": self._summary}}


class _NullSessionManager:
    def _save_session_to_disk(self, session) -> None:
        pass


def test_apply_compaction_keeps_exactly_what_was_not_summarised():
    session = _session_with(10)  # 20 messages
    to_compact = session.get_messages_to_compact()  # everything but the last 6
    assert len(to_compact) == 14
    summarised_texts = {m["content"] for m in to_compact}
    # The 6 messages the caller's snapshot said were NOT going to be
    # summarised — every one of them must still be there after apply.
    not_summarised_before = [m["content"] for m in session.messages[14:]]
    assert len(not_summarised_before) == 6

    # A user turn is appended AFTER the slice was measured, WHILE the (slow)
    # summarisation is "in flight" — simulated here by appending before apply.
    session.add_message("user", "un missatge nou mentre resumia")

    session.apply_compaction("resum", compacted_count=len(to_compact))

    kept_contents = [m["content"] for m in session.messages]
    # The old behaviour ("last COMPACT_KEEP at apply time") would have kept
    # only 6 messages total here, silently dropping the oldest of the 6 the
    # caller's snapshot said were safe — this is the exact bug C2.2 fixes.
    assert len(kept_contents) == 7, kept_contents
    for text in not_summarised_before:
        assert text in kept_contents, "a message the snapshot said was safe was dropped"
    assert "un missatge nou mentre resumia" in kept_contents, (
        "a message appended during the background summarisation must survive"
    )
    # Nothing from the summarised slice survives verbatim.
    assert not (summarised_texts & set(kept_contents))


def test_apply_compaction_without_compacted_count_keeps_old_behaviour():
    """`compacted_count=None` (the default) is the pre-C2.2 shape — any
    inline caller left standing must see it unchanged."""
    session = _session_with(10)
    session.apply_compaction("resum")
    assert len(session.messages) == session.COMPACT_KEEP


@pytest.mark.asyncio
async def test_compaction_applies_normally_when_not_preempted():
    session = _session_with(10)
    engine = _FixedWindowEngine("Resum aplicat.")
    await compact_session(session, engine, _NullSessionManager())
    assert session.context_summary == "Resum aplicat."
    assert session.compaction_count == 1


@pytest.mark.asyncio
async def test_preempted_compaction_does_not_apply():
    session = _session_with(10)
    before_summary = session.context_summary
    before_count = session.compaction_count
    engine = _FixedWindowEngine("Resum que no s'ha d'aplicar.")
    cancel = threading.Event()
    cancel.set()  # already preempted by the time the (fake) LLM call returns

    await compact_session(session, engine, _NullSessionManager(), cancel_event=cancel)

    assert session.context_summary == before_summary
    assert session.compaction_count == before_count


@pytest.mark.asyncio
async def test_not_preempted_ignores_an_unset_cancel_event():
    session = _session_with(10)
    engine = _FixedWindowEngine("Resum normal.")
    cancel = threading.Event()  # never set

    await compact_session(session, engine, _NullSessionManager(), cancel_event=cancel)

    assert session.context_summary == "Resum normal."
    assert session.compaction_count == 1
