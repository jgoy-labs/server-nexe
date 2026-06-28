"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/core/test_b216_queue_full_visible.py
Description: B216 — silent token loss on a full stream queue.

The engine thread calls ``TokenBridge.on_token`` for each token; the real
``put_nowait`` runs inside a ``call_soon_threadsafe`` callback on the event
loop. When the bounded queue is full, ``QueueFull`` was raised *inside* that
callback — outside the producer's try/except — and the token was dropped in
silence. The fix keeps the drop (drop > OOM, decision CS2) but makes it
VISIBLE: ``_truncated`` is marked and a single warning is logged, and the
downstream SSE close reports ``finish_reason="length"``.

MAX_STREAM_BYTES is kept high here so the byte cap (F33) never fires — this
suite is about the *queue* being full, not the byte budget.
────────────────────────────────────
"""
import asyncio
import threading

import pytest

from core.endpoints.chat_engines import _streaming
from core.endpoints.chat_engines._streaming import (
    TokenBridge,
    format_sse_done,
)


@pytest.mark.asyncio
async def test_queue_full_logs_warning_and_marks_truncated(monkeypatch, caplog):
    """A full queue must mark _truncated and emit exactly one warning."""
    # keep the byte cap far away so only the QueueFull path can trigger
    monkeypatch.setattr(_streaming, "MAX_STREAM_BYTES", 1024 * 1024 * 1024)

    bridge = TokenBridge(maxsize=2)

    # Fill the queue beyond capacity WITHOUT consuming it. on_token schedules
    # put_nowait via call_soon_threadsafe, so we must let the loop run the
    # callbacks (await asyncio.sleep(0)).
    with caplog.at_level("WARNING", logger="core.endpoints.chat_engines._streaming"):
        for i in range(6):  # maxsize=2 → tokens 3..6 overflow
            bridge.on_token(f"t{i}")
        for _ in range(10):
            await asyncio.sleep(0)  # drain the scheduled callbacks

    assert bridge._truncated is True
    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert len(warnings) == 1, f"expected exactly one warning, got {len(warnings)}"
    assert "truncat" in warnings[0].message.lower() or "queue full" in warnings[0].message.lower()


@pytest.mark.asyncio
async def test_slow_consumer_drops_token_but_never_blocks(monkeypatch):
    """A fast producer + slow consumer drops tokens but NEVER blocks (drop>OOM)."""
    monkeypatch.setattr(_streaming, "MAX_STREAM_BYTES", 1024 * 1024 * 1024)

    bridge = TokenBridge(maxsize=4)
    loop = asyncio.get_running_loop()
    N = 200
    produced_done = threading.Event()

    def _produce():
        # Real engine thread: push tokens as fast as possible. on_token must
        # never block this thread even when the queue is full.
        for i in range(N):
            bridge.on_token(f"tok{i}")
        # signal completion from the loop thread
        loop.call_soon_threadsafe(bridge.set_done)
        produced_done.set()

    consumed = []

    async def _consume():
        async for token in bridge:
            consumed.append(token)
            await asyncio.sleep(0.005)  # ~5ms/token: deliberately slow

    producer = threading.Thread(target=_produce, daemon=True)
    producer.start()

    # If on_token ever blocked, the producer would stall and the consumer would
    # wait forever → wait_for would raise TimeoutError. It must NOT.
    await asyncio.wait_for(_consume(), timeout=5)

    producer.join(timeout=2)
    assert produced_done.is_set(), "producer thread blocked — on_token is NOT non-blocking"
    # tokens were dropped (slow consumer, tiny queue) but visibly
    assert bridge._truncated is True
    assert 0 < len(consumed) < N
    # queue never grew unbounded: it is capped at maxsize
    assert bridge.queue.maxsize == 4


@pytest.mark.asyncio
async def test_truncation_propagates_to_finish_reason(monkeypatch):
    """When the bridge truncated, the stream close must report finish_reason=length."""
    monkeypatch.setattr(_streaming, "MAX_STREAM_BYTES", 1024 * 1024 * 1024)

    bridge = TokenBridge(maxsize=1)
    for i in range(5):
        bridge.on_token(f"t{i}")
    for _ in range(10):
        await asyncio.sleep(0)

    assert bridge._truncated is True

    # The downstream close formatter must reflect truncation. format_sse_done
    # should accept the bridge's truncation state and emit finish_reason=length.
    done_frame = format_sse_done("m", "llamacpp", truncated=bridge._truncated)
    assert '"finish_reason": "length"' in done_frame

    # And a non-truncated bridge still closes cleanly with "stop".
    clean = format_sse_done("m", "llamacpp", truncated=False)
    assert '"finish_reason": "stop"' in clean
