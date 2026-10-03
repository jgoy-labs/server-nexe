"""#1115: the root conftest still clears the auth and chat windows, and a
clear that raises is logged instead of swallowed.
"""

from __future__ import annotations

import logging

import conftest


def test_a_working_reset_clears_the_auth_window_and_stays_quiet(caplog):
    from core.security.auth_rate_limit import auth_failures

    auth_failures["9.9.9.9"] = [1.0]
    caplog.set_level(logging.WARNING, logger="conftest")
    conftest._clear_auth_and_chat_windows()
    assert "9.9.9.9" not in auth_failures
    assert not [
        record for record in caplog.records
        if record.name == "conftest" and record.levelno >= logging.WARNING
    ]


def test_duplicate_chat_limits_collapse_to_one():
    from core.dependencies import limiter

    key = "test-1115-route"
    previous = limiter._route_limits.get(key)
    limiter._route_limits[key] = ["20/minute", "20/minute"]
    try:
        conftest._clear_auth_and_chat_windows()
        assert limiter._route_limits[key] == ["20/minute"]
    finally:
        if previous is None:
            limiter._route_limits.pop(key, None)
        else:
            limiter._route_limits[key] = previous


def test_a_failed_auth_clear_is_logged_and_the_chat_reset_still_runs(monkeypatch, caplog):
    import core.security.auth_rate_limit as auth_rate_limit
    from core.dependencies import limiter

    class _Stuck(dict):
        def clear(self):
            raise RuntimeError("auth window stuck")

    monkeypatch.setattr(auth_rate_limit, "auth_failures", _Stuck())
    key = "test-1115-still-runs"
    limiter._route_limits[key] = ["20/minute", "20/minute"]
    caplog.set_level(logging.WARNING, logger="conftest")
    try:
        conftest._clear_auth_and_chat_windows()
    finally:
        limiter._route_limits.pop(key, None)

    warnings = [
        record for record in caplog.records
        if record.name == "conftest" and record.levelno == logging.WARNING
    ]
    assert any(
        "auth failure window was not cleared" in record.getMessage()
        and isinstance(record.exc_info[1], RuntimeError)
        for record in warnings
    )
    assert not any(
        "chat rate-limit window was not cleared" in record.getMessage()
        for record in warnings
    )


def test_a_failed_chat_reset_is_logged(monkeypatch, caplog):
    import core.dependencies as dependencies

    class _StuckLimiter:
        def reset(self):
            raise RuntimeError("limiter stuck")

        _route_limits: dict = {}

    monkeypatch.setattr(dependencies, "limiter", _StuckLimiter())
    caplog.set_level(logging.WARNING, logger="conftest")
    conftest._clear_auth_and_chat_windows()

    warnings = [
        record for record in caplog.records
        if record.name == "conftest" and record.levelno == logging.WARNING
    ]
    assert any(
        "chat rate-limit window was not cleared" in record.getMessage()
        and isinstance(record.exc_info[1], RuntimeError)
        for record in warnings
    )
    assert not any(
        "auth failure window was not cleared" in record.getMessage()
        for record in warnings
    )
