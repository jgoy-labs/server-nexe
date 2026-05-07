"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/test_qdrant_pool.py
Description: Tests for Bug 13 — flush before close in qdrant_pool and explicit
             error handling (replaces the `except: pass` that was hiding
             silent corruptions).

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
import logging
from unittest.mock import MagicMock

import pytest

import core.qdrant_pool as pool


@pytest.fixture(autouse=True)
def _reset_pool():
    pool._instances.clear()
    yield
    pool._instances.clear()


def test_close_calls_flush_then_close():
    """flush must be called BEFORE close, and both without errors."""
    client = MagicMock()
    call_order = []
    client.flush.side_effect = lambda: call_order.append("flush")
    client.close.side_effect = lambda: call_order.append("close")
    pool._instances["test:fake"] = client

    pool.close_qdrant_client()

    assert call_order == ["flush", "close"], (
        f"Expected order ['flush','close'], got {call_order}"
    )
    assert pool._instances == {}


def test_close_logs_warning_on_close_failure(caplog):
    """If close() raises, it is not swallowed: an explicit warning is logged.

    Previously there was `except Exception: pass` that was hiding any
    corruption or I/O error on close.
    """
    client = MagicMock()
    client.flush = MagicMock()  # flush ok
    client.close.side_effect = RuntimeError("disk full")
    pool._instances["test:broken"] = client

    with caplog.at_level(logging.WARNING, logger="core.qdrant_pool"):
        pool.close_qdrant_client()

    assert any(
        "Qdrant pool close failed" in rec.message
        and "disk full" in rec.message
        for rec in caplog.records
    ), f"Expected warning not found in logs: {[r.message for r in caplog.records]}"
    assert pool._instances == {}


def test_close_handles_missing_flush_gracefully(caplog):
    """If the client has no flush(), continues with close() without crashing."""
    client = MagicMock(spec=["close"])  # only close, no flush
    pool._instances["test:no-flush"] = client

    with caplog.at_level(logging.DEBUG, logger="core.qdrant_pool"):
        pool.close_qdrant_client()

    client.close.assert_called_once()
    assert pool._instances == {}


def test_close_logs_warning_on_flush_failure(caplog):
    """If flush() raises, it is logged but close() is still called."""
    client = MagicMock()
    client.flush.side_effect = RuntimeError("flush boom")
    pool._instances["test:flush-fail"] = client

    with caplog.at_level(logging.WARNING, logger="core.qdrant_pool"):
        pool.close_qdrant_client()

    # close() was called despite the flush failing
    client.close.assert_called_once()
    assert any(
        "flush" in rec.message.lower() for rec in caplog.records
    )
