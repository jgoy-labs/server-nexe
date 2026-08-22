"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: memory/memory/api/_budget.py
Description: Declared time budget for memory READS (#890).

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import asyncio
import logging
import os
from typing import Awaitable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Reads live inside a chat request: the user is waiting with the cursor
# blinking. Writes get 30s (documents.py) because they happen in the
# background; a read that takes longer than this budget has already lost the
# turn it was serving. The embedder is pre-warmed at startup
# (_prewarm_fastembed), so this budget does not have to pay a cold start.
DEFAULT_READ_TIMEOUT = 8.0

ENV_READ_TIMEOUT = "NEXE_MEMORY_READ_TIMEOUT"


class MemoryReadTimeout(RuntimeError):
    """A memory read ran out of its budget.

    A RuntimeError on purpose: every caller on the chat path already treats a
    failing memory read as "answer without context" (chat_rag.py,
    routes_chat.py), and the write path already converts its own timeout into a
    RuntimeError. A hang, unlike an exception, was reaching none of those
    guards — which is the whole of #890.
    """


def read_timeout() -> float:
    """Seconds a memory read may take. Read per call, not at import time."""
    raw = os.getenv(ENV_READ_TIMEOUT)
    if raw is None or not raw.strip():
        return DEFAULT_READ_TIMEOUT
    try:
        value = float(raw.strip())
    except ValueError:
        logger.warning(
            "%s=%r is not a number; using %.1fs", ENV_READ_TIMEOUT, raw,
            DEFAULT_READ_TIMEOUT,
        )
        return DEFAULT_READ_TIMEOUT
    if value <= 0:
        logger.warning(
            "%s=%s must be positive; using %.1fs", ENV_READ_TIMEOUT, value,
            DEFAULT_READ_TIMEOUT,
        )
        return DEFAULT_READ_TIMEOUT
    return value


async def within_read_budget(awaitable: Awaitable[T], what: str) -> T:
    """Await under the read budget, or fail saying which step ran out.

    Note what this does NOT do: a blocking call already handed to the executor
    keeps running in its thread after the budget expires. The budget protects
    the REQUEST, not the worker — Qdrant's own client offers no cancellation.
    """
    budget = read_timeout()
    try:
        return await asyncio.wait_for(awaitable, timeout=budget)
    except asyncio.TimeoutError:
        raise MemoryReadTimeout(
            f"memory read timed out after {budget}s ({what}); "
            f"raise {ENV_READ_TIMEOUT} if this store is legitimately slower"
        ) from None


__all__ = [
    "DEFAULT_READ_TIMEOUT",
    "ENV_READ_TIMEOUT",
    "MemoryReadTimeout",
    "read_timeout",
    "within_read_budget",
]
