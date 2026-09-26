"""#998: NEXE_HISTORY_CONTEXT_RATIO above 0.9 is clamped — and now says so.

`_ratio_env` accepts (0, 1]; `compute_context_budget` clamps the ratio to 0.9.
A value in (0.9, 1] used to be cut down in silence. The behaviour stays (the
clamp is where it was); what is pinned here is the WARNING, logged once per
process, and that nothing is logged for a value that is not clamped.
"""
from __future__ import annotations

import logging

import pytest

import core.context_budget as cb


@pytest.fixture(autouse=True)
def _fresh_flag(monkeypatch):
    monkeypatch.setattr(cb, "_warned_history_clamp", False)


def _clamp_warnings(caplog):
    return [
        r for r in caplog.records
        if r.levelno == logging.WARNING and "clamped to 0.9" in r.getMessage()
    ]


def test_a_value_above_the_ceiling_warns_once(monkeypatch, caplog):
    monkeypatch.setenv("NEXE_HISTORY_CONTEXT_RATIO", "0.95")
    with caplog.at_level(logging.WARNING, logger="core.context_budget"):
        first = cb.resolve_history_ratio()
        second = cb.resolve_history_ratio()
    # No behaviour change: the value is returned as read.
    assert first == second == 0.95
    warnings = _clamp_warnings(caplog)
    assert len(warnings) == 1
    assert "NEXE_HISTORY_CONTEXT_RATIO=0.95" in warnings[0].getMessage()


def test_a_value_under_the_ceiling_is_silent(monkeypatch, caplog):
    monkeypatch.setenv("NEXE_HISTORY_CONTEXT_RATIO", "0.5")
    with caplog.at_level(logging.WARNING, logger="core.context_budget"):
        assert cb.resolve_history_ratio() == 0.5
    assert _clamp_warnings(caplog) == []


def test_the_clamp_itself_is_unchanged():
    kwargs = dict(
        max_context_chars=20_000, system_chars=1_000, history_chars=15_000,
        message_chars=100, document_chars=10_000,
    )
    assert cb.compute_context_budget(**kwargs, history_ratio=0.95) == \
        cb.compute_context_budget(**kwargs, history_ratio=0.9)
    assert cb.compute_context_budget(**kwargs, history_ratio=0.95) != \
        cb.compute_context_budget(**kwargs, history_ratio=0.5)
