"""Anti-regression scenario — `RAGCLI.module` post-init guard.

Covers the 5 mypy `union-attr` findings at `memory/rag/cli.py:59, 108, 185, 217, 229`.
All are `Item "None" of "RAGModule | None" has no attribute X` because
`self.module: Optional[RAGModule] = None` (cli.py:31) and `cmd_*` called before
`initialize()` access `self.module.X()` directly.

design decision (scenario): dev introduces helper `_require_module(self) -> RAGModule`
that raises `RuntimeError("RAG not initialized")` and replaces `self.module.X()` with
`self._require_module().X()` at the 5 callsites.

PINNED CONTRACT:
1. `RAGCLI()` post-construction has `self.module is None` (bug premise).
2. `cmd_info`, `cmd_health`, `cmd_search`, `cmd_sources` are `async def`
   (since all use `await` or expect an async module). scenario fix must NOT change
   their external signatures.
3. Called without initialize, they return `1` (graceful failure via global try/except)
   instead of propagating an exception. This contract holds pre and post-fix:
   pre-fix `AttributeError` → except → return 1; post-fix `RuntimeError` → except → return 1.

Pre-fix (HEAD `30eb2a6`): runtime contract is fulfilled thanks to try/except.
Post-fix: must continue to be fulfilled. If dev removes the try/except (out-of-scope),
the suite detects the regression.
"""

from __future__ import annotations

import asyncio
import inspect

import pytest


def test_ragcli_module_optional_at_init() -> None:
    """`RAGCLI()` must have `self.module is None` post-construction.

    This test pins the cluster premise: the field exists as `Optional` and
    starts at None. If dev changes the type or initial value (e.g., to a
    dummy instance), it breaks the bug condition and invalidates the proposed helper."""
    from memory.rag.cli import RAGCLI

    cli = RAGCLI()
    assert cli.module is None, (
        "RAGCLI.__init__ no longer initialises module to None — scenario premise broken."
    )


def test_ragcli_async_methods_signatures_pinned() -> None:
    """Pins that the 4 affected `cmd_*` methods remain async and take `args`.

    The mypy findings are at cli.py:59 (cmd_info), 108 (cmd_health), 185 (cmd_search),
    217 + 229 (cmd_sources). If dev changes signatures (e.g. adding `module: RAGModule`
    as a parameter to avoid the guard), it breaks all callers via `argparse`."""
    from memory.rag.cli import RAGCLI

    for method_name in ("cmd_info", "cmd_health", "cmd_search", "cmd_sources"):
        method = getattr(RAGCLI, method_name, None)
        assert method is not None, f"RAGCLI.{method_name} has disappeared."
        assert inspect.iscoroutinefunction(method), (
            f"RAGCLI.{method_name} has lost `async def` — out-of-scope scenario."
        )
        sig = inspect.signature(method)
        # `self` + `args`
        assert len(sig.parameters) == 2, (
            f"Signature RAGCLI.{method_name}{sig} has changed — expected (self, args)."
        )


def test_ragcli_cmd_info_returns_one_without_initialize() -> None:
    """Behavioural anti-regression: `cmd_info` called without `initialize()`
    completes with return 1 (does not propagate exception outward).

    Pre-fix: AttributeError caught by try/except → return 1.
    Post-fix: RuntimeError caught by try/except → return 1.
    If dev removes the global try/except from cmd_info, the test FAILS."""
    from memory.rag.cli import RAGCLI

    cli = RAGCLI()
    assert cli.module is None  # precondition

    # cmd_info takes `args` but does not use it, we can pass None
    rc = asyncio.run(cli.cmd_info(args=None))
    assert rc == 1, (
        f"cmd_info without initialize returned {rc} (expected 1). "
        "The global try/except has been removed or the post-fix helper propagates."
    )


def test_ragcli_cmd_health_returns_one_without_initialize() -> None:
    """Identical anti-regression for cmd_health."""
    from memory.rag.cli import RAGCLI

    cli = RAGCLI()
    rc = asyncio.run(cli.cmd_health(args=None))
    assert rc == 1
