"""B075-C1: core/uptime.py is the single source of truth for server uptime.

The health endpoints used to report a fixed label ("operational" / "available")
dressed up as a metric. These tests pin the real behaviour: whole-second strings
that grow monotonically. A mutation that returns a constant (e.g. "operational")
makes ``isdigit()`` / the monotonic assert fail.
"""
from __future__ import annotations

import time

from core.uptime import uptime_seconds, uptime_str


def test_uptime_seconds_is_nonnegative_float():
    v = uptime_seconds()
    assert isinstance(v, float)
    assert v >= 0.0


def test_uptime_str_is_whole_seconds():
    s = uptime_str()
    assert s.isdigit(), f"uptime_str must be whole seconds, got {s!r}"
    assert int(s) >= 0


def test_uptime_grows_monotonically():
    before = uptime_seconds()
    time.sleep(0.02)
    after = uptime_seconds()
    assert after >= before, "uptime must not go backwards"
    assert after > before, "uptime must advance with wall time"


def test_uptime_uses_os_process_start_not_import_marker(monkeypatch):
    """B075-C1 refinement: the value is the TRUE process age (OS create_time), not
    a marker captured when this module was imported — which in production
    under-reports by the whole module-load / RAG-warmup window before this late
    import runs.

    Deterministic + mutation-proof: pin a fake process start 1000s in the past.
    The correct code (time.time() - _PROC.create_time()) yields ~1000; a mutation
    reverting to the import-time monotonic marker yields a few seconds → RED.
    """
    import core.uptime as up

    if not up._HAVE_PSUTIL:
        import pytest
        pytest.skip("psutil unavailable; OS process-time path not exercised")

    fake_start = time.time() - 1000.0
    monkeypatch.setattr(up._PROC, "create_time", lambda: fake_start)
    v = up.uptime_seconds()
    assert 995.0 < v < 1005.0, f"uptime must reflect OS create_time (~1000s), got {v}"
