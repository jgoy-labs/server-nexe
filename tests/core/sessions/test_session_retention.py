"""Conversations are kept unless the owner asks for a retention (13/10/2026:
the hourly cleanup deleted 837 of them, all older than 24 h, an hour after
the server was started)."""
import asyncio

import pytest

from core.sessions import cleanup
from core.sessions.cleanup import RETENTION_ENV, retention_hours


@pytest.mark.parametrize("value", [None, "", "  ", "0", "-3", "abc", "1.5"])
def test_no_retention_means_never(monkeypatch, value):
    if value is None:
        monkeypatch.delenv(RETENTION_ENV, raising=False)
    else:
        monkeypatch.setenv(RETENTION_ENV, value)
    assert retention_hours() is None


@pytest.mark.parametrize("days, hours", [("1", 24), ("30", 720), (" 7 ", 168)])
def test_a_positive_number_of_days(monkeypatch, days, hours):
    monkeypatch.setenv(RETENTION_ENV, days)
    assert retention_hours() == hours


class _Mgr:
    def __init__(self):
        self.calls = []

    def cleanup_inactive(self, max_age_hours):
        self.calls.append(max_age_hours)
        return 0


async def _rounds(mgr, rounds, monkeypatch):
    """Run the real loop for `rounds` ticks (sleep made instant)."""
    ticks = {"n": 0}

    async def fast_sleep(_):
        ticks["n"] += 1
        if ticks["n"] > rounds:
            raise asyncio.CancelledError
    monkeypatch.setattr(cleanup.asyncio, "sleep", fast_sleep)
    with pytest.raises(asyncio.CancelledError):
        await cleanup._session_cleanup_loop(mgr)


def test_the_loop_deletes_nothing_by_default(monkeypatch):
    monkeypatch.delenv(RETENTION_ENV, raising=False)
    mgr = _Mgr()
    asyncio.run(_rounds(mgr, 3, monkeypatch))
    assert mgr.calls == []


def test_the_loop_deletes_with_the_asked_retention(monkeypatch):
    monkeypatch.setenv(RETENTION_ENV, "30")
    mgr = _Mgr()
    asyncio.run(_rounds(mgr, 2, monkeypatch))
    assert mgr.calls == [720, 720]
