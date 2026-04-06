"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/test_qdrant_pool.py
Description: Tests per Bug 13 — flush abans de close al qdrant_pool i error
             handling explicit (substitueix el `except: pass` que amagava
             corrupcions silencioses).

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
    """flush ha de cridar-se ABANS de close, i ambdos sense errors."""
    client = MagicMock()
    call_order = []
    client.flush.side_effect = lambda: call_order.append("flush")
    client.close.side_effect = lambda: call_order.append("close")
    pool._instances["test:fake"] = client

    pool.close_qdrant_client()

    assert call_order == ["flush", "close"], (
        f"Order esperat ['flush','close'], rebut {call_order}"
    )
    assert pool._instances == {}


def test_close_logs_warning_on_close_failure(caplog):
    """Si close() llanca, no s'engoleix: es loguea un warning explicit.

    Abans hi havia `except Exception: pass` que amagava qualsevol
    corrupcio o error de I/O al tancament.
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
    ), f"No s'ha trobat el warning esperat als logs: {[r.message for r in caplog.records]}"
    assert pool._instances == {}


def test_close_handles_missing_flush_gracefully(caplog):
    """Si el client no te flush(), continua amb close() sense petar."""
    client = MagicMock(spec=["close"])  # nomes close, sense flush
    pool._instances["test:no-flush"] = client

    with caplog.at_level(logging.DEBUG, logger="core.qdrant_pool"):
        pool.close_qdrant_client()

    client.close.assert_called_once()
    assert pool._instances == {}


def test_close_logs_warning_on_flush_failure(caplog):
    """Si flush() llanca, es loguea pero close() es crida igualment."""
    client = MagicMock()
    client.flush.side_effect = RuntimeError("flush boom")
    pool._instances["test:flush-fail"] = client

    with caplog.at_level(logging.WARNING, logger="core.qdrant_pool"):
        pool.close_qdrant_client()

    # close() s'ha cridat tot i el flush fallat
    client.close.assert_called_once()
    assert any(
        "flush" in rec.message.lower() for rec in caplog.records
    )
