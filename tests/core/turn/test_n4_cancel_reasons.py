"""C4.8 N4: the turn's cancel event says WHY it was set.

The disconnect monitor and the deadline timer set the same event (an engine
stops alike for both), and the cascade asks no other engine only when the
client left (`engine_claim._cancelled`). These pin the event and the monitor;
the doors are pinned by the matrix's `gone` cells and
`test_c48_p0_rows.test_n4_a_turn_that_ran_out_of_time_is_not_a_client_that_left`.
"""
from __future__ import annotations

import asyncio
import threading

from core.turn.cancel import CLIENT_GONE, DEADLINE, TurnCancel, client_gone, start_disconnect_monitor


class _Request:
    """A client that is there for `stays` polls, then gone."""

    def __init__(self, stays: int) -> None:
        self.stays = stays
        self.polls = 0

    async def is_disconnected(self) -> bool:
        self.polls += 1
        return self.polls > self.stays


def test_the_event_is_still_an_event_for_the_engines():
    event = TurnCancel()
    assert isinstance(event, threading.Event) and not event.is_set() and event.reasons == set()
    event.cancel(DEADLINE)
    assert event.is_set() and event.reasons == {DEADLINE}
    assert not client_gone(event)


def test_a_plain_set_says_nothing_about_the_client():
    event = TurnCancel()
    event.set()
    assert event.is_set() and not client_gone(event)
    plain = threading.Event()
    plain.set()
    assert not client_gone(plain) and not client_gone(None)


async def test_the_monitor_marks_a_client_that_left():
    event, task = start_disconnect_monitor(_Request(stays=0))
    await asyncio.wait_for(task, 2)
    assert client_gone(event) and event.reasons == {CLIENT_GONE}


async def test_a_client_that_leaves_after_the_deadline_is_still_marked():
    """The monitor keeps watching once the deadline has set the event: a client
    that leaves later is a client that left, and the cascade stops for it."""
    request = _Request(stays=1)
    event, task = start_disconnect_monitor(request)
    event.cancel(DEADLINE)
    await asyncio.wait_for(task, 3)
    assert event.reasons == {DEADLINE, CLIENT_GONE}
    assert request.polls == 2


# ── P2-1: each engine of the cascade is handed an event of its own ──────────

async def test_an_engines_event_is_reached_by_what_sets_the_turns():
    turn = TurnCancel()
    engine = turn.attempt()
    assert engine.turn is turn and not engine.is_set()
    turn.cancel(CLIENT_GONE)
    assert engine.is_set() and client_gone(engine)
    capped = TurnCancel()
    later = capped.attempt()
    capped.set()  # the byte cap: no reason, and it reaches the engine that is answering
    assert later.is_set() and later.reasons == set()


async def test_an_engine_asked_after_the_turns_event_was_set_starts_with_it_set():
    turn = TurnCancel()
    turn.cancel(CLIENT_GONE)
    engine = turn.attempt()
    assert engine.is_set() and client_gone(engine)


async def test_the_deadline_one_engine_used_up_is_not_the_next_ones():
    turn = TurnCancel()
    turn.deadline_s = 0.05
    first = turn.attempt()
    await asyncio.sleep(0.15)
    assert first.reasons == {DEADLINE} and not turn.is_set()
    second = turn.attempt()
    assert not second.is_set() and second.deadline_armed
    second.disarm_deadline()  # its first byte
    await asyncio.sleep(0.1)
    assert not second.is_set()


async def test_the_end_of_the_hold_disarms_every_engines_deadline():
    turn = TurnCancel()
    turn.deadline_s = 0.05
    engine = turn.attempt()
    turn.disarm_deadline()
    await asyncio.sleep(0.15)
    assert not engine.is_set() and not turn.deadline_armed
