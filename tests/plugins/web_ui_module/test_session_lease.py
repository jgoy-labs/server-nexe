"""C2.3 (ADR-007 §9, I9): a session has one live writer.

Before this, `apply_compaction` running in the background (C2.2) and two
doors writing the same session had zero coordination — exactly the silent
race #992 (check-then-act on session creation), #997 (the /v1 mirror wiping
a UI thread's state) and #996 already described independently. The lease
closes all three the same way: at most one live USER writer ("ui"/"api") per
session, refused with the current lease unless the caller explicitly takes
over (`force=True`).

Deliberately NOT tested here: background jobs never call `acquire_lease` at
all (see the method's own docstring) — their interaction with a live turn is
the engine gate (C2.1) and `PostCommitQueue.preempt` (C2.2), already covered
by `test_engine_gate.py` / `test_post_commit_queue.py`.

Mutation check (exercised by hand before merging, see the diari): removing
the `_sessions_lock` from `acquire_lease` — measured 5/5 GREEN on
`test_two_concurrent_acquires_only_one_wins` even with the lock replaced by
a no-op (the critical section is microseconds long; two real threads racing
it under the GIL is not a reliable way to catch this). The structural test
below (`test_acquire_lease_actually_uses_the_sessions_lock`) is what
actually turns red.
"""
from __future__ import annotations

import threading
import time

import pytest

from core.sessions.session_manager import DEFAULT_LEASE_TTL_S, SessionManager


@pytest.fixture
def manager(tmp_path, monkeypatch):
    monkeypatch.setenv("NEXE_ENV", "development")  # plaintext .json, no crypto needed
    return SessionManager(storage_path=str(tmp_path / "sessions"))


def test_first_acquire_on_a_fresh_session_is_granted(manager):
    session = manager.create_session("s1")
    result = manager.acquire_lease(session.id, holder="ui", turn_id="t1", where="web UI")
    assert result.granted
    assert result.lease["holder"] == "ui"
    assert result.lease["turn_id"] == "t1"
    assert session.lease == result.lease


def test_a_second_turn_is_refused_with_the_blocking_lease(manager):
    session = manager.create_session("s1")
    manager.acquire_lease(session.id, holder="ui", turn_id="t1", where="web UI")
    result = manager.acquire_lease(session.id, holder="api", turn_id="t2", where="API")
    assert not result.granted
    assert result.lease["turn_id"] == "t1"
    assert result.lease["where"] == "web UI"


def test_renewing_the_same_turn_id_is_always_granted(manager):
    session = manager.create_session("s1")
    manager.acquire_lease(session.id, holder="ui", turn_id="t1", where="web UI")
    result = manager.acquire_lease(session.id, holder="ui", turn_id="t1", where="web UI")
    assert result.granted


def test_an_expired_lease_is_granted_to_a_new_turn(manager):
    session = manager.create_session("s1")
    manager.acquire_lease(session.id, holder="ui", turn_id="t1", where="web UI", ttl_s=0.01)
    time.sleep(0.02)
    result = manager.acquire_lease(session.id, holder="api", turn_id="t2", where="API")
    assert result.granted
    assert result.lease["turn_id"] == "t2"


def test_force_takes_over_a_live_lease(manager):
    session = manager.create_session("s1")
    manager.acquire_lease(session.id, holder="ui", turn_id="t1", where="web UI")
    result = manager.acquire_lease(session.id, holder="ui", turn_id="t2", where="mobile app", force=True)
    assert result.granted
    assert result.lease["turn_id"] == "t2"
    assert session.lease["turn_id"] == "t2"


def test_release_only_by_the_current_holder(manager):
    session = manager.create_session("s1")
    manager.acquire_lease(session.id, holder="ui", turn_id="t1", where="web UI")
    manager.release_lease(session.id, "t-not-the-holder")  # a stale/preempted caller
    assert session.lease is not None, "a non-holder's release must not clear the CURRENT lease"
    manager.release_lease(session.id, "t1")
    assert session.lease is None


def test_release_on_a_session_with_no_lease_is_a_no_op(manager):
    session = manager.create_session("s1")
    manager.release_lease(session.id, "t1")  # must not raise
    assert session.lease is None


def test_renew_extends_expiry_only_for_the_holder(manager):
    session = manager.create_session("s1")
    manager.acquire_lease(session.id, holder="ui", turn_id="t1", where="web UI", ttl_s=0.05)
    assert manager.renew_lease(session.id, "t1", ttl_s=DEFAULT_LEASE_TTL_S) is True
    time.sleep(0.1)
    # Would have expired at the original 0.05s TTL — the renewal must have
    # pushed it out to the (much longer) default.
    result = manager.acquire_lease(session.id, holder="api", turn_id="t2", where="API")
    assert not result.granted

    assert manager.renew_lease(session.id, "not-the-holder", ttl_s=1.0) is False


def test_acquire_on_an_unknown_session_id_is_granted_with_no_lease_object(manager):
    """The door resolves/creates the session and calls acquire_lease right
    after, under the same re-entrant lock — this is not a bypass, just the
    ordering `get_or_create_session` → `acquire_lease` in the real adapters."""
    result = manager.acquire_lease("never-created", holder="ui", turn_id="t1", where="web UI")
    assert result.granted
    assert result.lease is None


def test_acquire_lease_actually_uses_the_sessions_lock(manager):
    """Structural, not timing-based: two real threads racing a microseconds-
    long critical section is not a reliable way to catch "someone removed
    the lock" under the GIL (measured: 5/5 green even with the lock replaced
    by a no-op). This asserts the lock is actually entered and exited —
    exactly what the mutation (dropping `with self._sessions_lock:`) removes.
    """
    session = manager.create_session("s1")
    calls: list[str] = []
    real_lock = manager._sessions_lock

    class _SpyLock:
        def __enter__(self):
            calls.append("enter")
            return real_lock.__enter__()

        def __exit__(self, *exc):
            calls.append("exit")
            return real_lock.__exit__(*exc)

    manager._sessions_lock = _SpyLock()
    manager.acquire_lease(session.id, holder="ui", turn_id="t1", where="web UI")
    assert calls == ["enter", "exit"], "acquire_lease must take the sessions lock exactly once"


def test_two_concurrent_acquires_only_one_wins(manager):
    session = manager.create_session("s1")
    results: list = []
    barrier = threading.Barrier(2)

    def attempt(turn_id: str):
        barrier.wait()
        results.append(manager.acquire_lease(session.id, holder="ui", turn_id=turn_id, where="web UI"))

    threads = [threading.Thread(target=attempt, args=(f"t{i}",)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    granted = [r for r in results if r.granted]
    assert len(granted) == 1, "exactly one concurrent acquire must win"


def test_list_sessions_reports_the_lease_holder(manager):
    session = manager.create_session("s1")
    manager.acquire_lease(session.id, holder="ui", turn_id="t1", where="web UI")
    rows = manager.list_sessions()
    row = next(r for r in rows if r["id"] == session.id)
    assert row["lease_holder"] == "ui"
    assert row["lease_where"] == "web UI"


def test_lease_never_survives_a_disk_roundtrip(manager, tmp_path):
    """A lease means "live in THIS process" — one written to disk (to_dict
    does include it) must never come back on load (from_dict never reads
    it), or a lock from a process that no longer exists could never be
    released."""
    session = manager.create_session("s1")
    manager.acquire_lease(session.id, holder="ui", turn_id="t1", where="web UI")
    manager.save_session(session.id)

    from core.sessions.session_manager import ChatSession
    saved = ChatSession.from_dict(session.to_dict())
    assert saved.lease is None
