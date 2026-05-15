"""Anti-regression for `folder` ingest_knowledge (, refactor).

Covers mypy findings #31, #37, #40. Pins the
signature contract: `ingest_knowledge(folder=None, ...)` must continue
accepting None as the default value (to use the PROJECT_ROOT/knowledge
fallback documented in the function docstring).

The dev fix will change the annotation `folder: Path = None` to
`folder: Optional[Path] = None`. The default value (None) *does not change*;
only the static annotation. This test pins the runtime contract: pre-fix passes
(default is already None) and post-fix continues to pass.

CEC: signature only. The function body is NOT executed (the coroutine is created
and closed without awaiting).
"""

from __future__ import annotations

import asyncio
import inspect


def test_ingest_knowledge_folder_default_is_none() -> None:
    """Pins signature contract: `folder` default = None."""
    from core.ingest.ingest_knowledge import ingest_knowledge

    sig = inspect.signature(ingest_knowledge)
    assert "folder" in sig.parameters, (
        "ingest_knowledge has lost the `folder` parameter — breaks cluster #31."
    )
    folder_param = sig.parameters["folder"]
    assert folder_param.default is None, (
        f"ingest_knowledge.folder.default = {folder_param.default!r}, expected None. "
        "The fix must keep the default at None and only change "
        "the annotation to Optional[Path]."
    )


def test_ingest_knowledge_accepts_explicit_none() -> None:
    """Pins call contract: `ingest_knowledge(folder=None)` does not raise
    a binding TypeError (cf. scripts/bench_ingest_bug16.py:107 #40 and
    `core/ingest/ingest_knowledge.py:562` #37 which pass folder=None).

    CEC: the coroutine is closed without executing the body.
    """
    from core.ingest.ingest_knowledge import ingest_knowledge

    sig = inspect.signature(ingest_knowledge)
    bound = sig.bind(folder=None)
    bound.apply_defaults()
    assert bound.arguments["folder"] is None
    assert bound.arguments["quiet"] is False

    coro = ingest_knowledge(folder=None)
    try:
        assert asyncio.iscoroutine(coro)
    finally:
        coro.close()
