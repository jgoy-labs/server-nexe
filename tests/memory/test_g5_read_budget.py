"""G5 (#890) — a memory read that hangs must lose, not wait forever.

Every guard on the chat path caught memory failures as EXCEPTIONS
(chat_rag.py:123-127, routes_chat.py:1639-1673) and the write path had a 30s
ceiling since forever. The read path had none: documents.search() awaited
generate_embedding() and then run_in_executor() with no budget, so a Qdrant or
an embedder that HANGS — the .lock held by another process, a socket that
accepts and never answers — walked through all of them. A try/except does not
catch a block.

Each test drives the real search() and puts its OWN outer deadline on it. That
outer deadline is what makes the gate honest: without the fix the test does not
hang forever waiting for a verdict, it fails, and it fails saying that nothing
inside the read ever gave up.
"""
from __future__ import annotations

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock

import pytest

from memory.memory.api._budget import (
    DEFAULT_READ_TIMEOUT,
    ENV_READ_TIMEOUT,
    MemoryReadTimeout,
    read_timeout,
    within_read_budget,
)
from memory.memory.api.documents import search_documents as search

OUTER_DEADLINE = 5.0  # generous: the budget under test is set to 0.3s


@pytest.fixture()
def short_budget(monkeypatch):
    monkeypatch.setenv(ENV_READ_TIMEOUT, "0.3")


@pytest.fixture()
def executor():
    ex = ThreadPoolExecutor(max_workers=1)
    yield ex
    ex.shutdown(wait=False)


async def _never_returns(_text):
    """An embedder that accepts the call and never answers."""
    await asyncio.Event().wait()


async def _instant(_text):
    return [0.1, 0.2, 0.3]


@pytest.mark.asyncio
async def test_a_hanging_embedder_gives_up_within_budget(short_budget, executor):
    """The step that hangs is named, and the read ends."""
    with pytest.raises(MemoryReadTimeout, match="embedding the query"):
        await asyncio.wait_for(
            search(
                qdrant=MagicMock(),
                executor=executor,
                generate_embedding=_never_returns,
                query="hola",
                collection="user_knowledge",
            ),
            timeout=OUTER_DEADLINE,
        )


@pytest.mark.asyncio
async def test_a_hanging_store_gives_up_within_budget(short_budget, executor):
    """Same for the Qdrant call itself, which runs in a worker thread."""
    # Blocks well past the 0.3s budget, but not so long that the worker thread
    # outlives the test: the budget frees the REQUEST, never the thread, and a
    # 30s sleeper would hold the interpreter at exit.
    import threading

    def _blocks(*_a, **_k):
        threading.Event().wait(2.0)
        raise AssertionError("the budget should have fired long before this")

    qdrant = MagicMock()
    qdrant.query_points.side_effect = _blocks
    qdrant.search.side_effect = _blocks

    with pytest.raises(MemoryReadTimeout, match="searching"):
        await asyncio.wait_for(
            search(
                qdrant=qdrant,
                executor=executor,
                generate_embedding=_instant,
                query="hola",
                collection="user_knowledge",
            ),
            timeout=OUTER_DEADLINE,
        )


@pytest.mark.asyncio
async def test_a_healthy_read_is_not_cut(short_budget, executor):
    """Calibration: a budget that fires on a working store is a broken product,
    not a gate. Without this, `raise` on every read would look green."""
    qdrant = MagicMock()
    qdrant.query_points.return_value = MagicMock(points=[])
    qdrant.search.return_value = []

    result = await asyncio.wait_for(
        search(
            qdrant=qdrant,
            executor=executor,
            generate_embedding=_instant,
            query="hola",
            collection="user_knowledge",
        ),
        timeout=OUTER_DEADLINE,
    )
    assert result == []


@pytest.mark.asyncio
async def test_a_synchronous_blocker_off_executor_is_not_cut(monkeypatch):
    """#955, verified 26/08/2026: the budget only cuts a hang that yields
    control back to the loop. asyncio.wait_for cannot interrupt code that
    never awaits — a caller that runs a blocking store call IN-LOOP, without
    handing it to an executor, blows straight through the budget AND holds
    the whole event loop hostage, not just this request. documents.py avoids
    this today by wrapping its Qdrant call in run_in_executor (search()
    above proves that path is cut); a future read path that skips that
    wrapping is exactly the case this test would need to catch, and — being
    itself in-loop — cannot. Known limit of the protection, not a live bug:
    pinned here so the limit stays visible in CI instead of only in a report.
    """
    monkeypatch.setenv(ENV_READ_TIMEOUT, "0.05")

    async def _blocks_the_loop_directly():
        time.sleep(0.3)  # never yields — no executor, no real await inside
        return "arrived anyway"

    started = time.monotonic()
    result = await asyncio.wait_for(
        within_read_budget(_blocks_the_loop_directly(), "test probe"),
        timeout=OUTER_DEADLINE,
    )
    elapsed = time.monotonic() - started

    assert result == "arrived anyway", (
        "a 0.05s budget did not fire on a 0.3s in-loop sleep — if this starts "
        "raising MemoryReadTimeout, either wait_for started pre-empting "
        "synchronous code or the scenario no longer reproduces; update the "
        "docstring above, don't just delete the assert"
    )
    assert elapsed >= 0.3, (
        "the in-loop sleep finished faster than it should have — this test's "
        "premise (a call that never yields) no longer holds"
    )


def test_the_budget_is_read_per_call_not_at_import(monkeypatch):
    """A budget frozen at import time cannot be changed by whoever runs the
    server — and could not be exercised by these tests either."""
    assert read_timeout() == DEFAULT_READ_TIMEOUT
    monkeypatch.setenv(ENV_READ_TIMEOUT, "1.5")
    assert read_timeout() == 1.5


@pytest.mark.parametrize("bad", ["", "   ", "nonsense", "0", "-3"])
def test_a_broken_setting_falls_back_to_the_default(monkeypatch, bad):
    """An unusable value must not disable the ceiling: that is how #890 looked
    in the first place."""
    monkeypatch.setenv(ENV_READ_TIMEOUT, bad)
    assert read_timeout() == DEFAULT_READ_TIMEOUT


def test_the_default_is_pinned_to_the_config_catalog():
    """Two sources of truth are only acceptable while something fails when they
    disagree (#888's lesson, applied here).

    The catalog is what the product documents and what /admin lists; _budget.py
    is what actually runs. A drift between them would advertise one ceiling and
    enforce another.
    """
    from core.config_catalog import default_for

    assert default_for("memory_read_timeout") == DEFAULT_READ_TIMEOUT, (
        "core/config_catalog.py and memory/memory/api/_budget.py disagree on "
        "the read budget"
    )
