"""Anti-regression cluster `_stream_kwargs` chat_cli (Onada 4.1, BUS Dev#1bis).

Covers mypy findings #20, #23, #25, #27 (`01-classificacio.md`). Mypy
infers `_stream_kwargs: dict[str, float]` from the first assignment
(`rag_threshold = float`) and flags the second (`rag_collections = list[str]`).
The Dev#2 fix (Cluster 5) explicitly annotates `_stream_kwargs: dict[str, Any] = {}`.

The only observable runtime behaviour is the unpacking `**_stream_kwargs`
on `client.chat_ui_stream(...)`. This test pins:

1. `NexeAPIClient.chat_ui_stream` accepts `rag_threshold` (Optional[float]) and
   `rag_collections` (Optional[list]) as kwargs (stable signature, does not change
   with the Dev#2 fix).
2. A heterogeneous dict `{'rag_threshold': 0.5, 'rag_collections': [...]}` can
   bind to this signature without TypeError — exactly the `**_stream_kwargs`
   pattern from chat_cli.

If Dev#2 inadvertently touches the client signature (out-of-scope), this test
fails — *teeth* against collateral refactor.

CEC: `inspect.signature` + `Signature.bind` only. No real invocation.
"""

from __future__ import annotations

import inspect


def test_chat_ui_stream_accepts_rag_kwargs() -> None:
    """Pins signature: `chat_ui_stream` declares `rag_threshold` and `rag_collections`."""
    from core.cli.utils.api_client import NexeAPIClient

    sig = inspect.signature(NexeAPIClient.chat_ui_stream)
    params = sig.parameters
    assert "rag_threshold" in params, (
        "NexeAPIClient.chat_ui_stream has lost `rag_threshold` — "
        "breaks cluster _stream_kwargs."
    )
    assert "rag_collections" in params, (
        "NexeAPIClient.chat_ui_stream has lost `rag_collections` — "
        "breaks cluster _stream_kwargs."
    )


def test_stream_kwargs_unpack_pattern_binds() -> None:
    """Pins invocation contract: the exact pattern from chat_cli.py:259-263 +
    320/334/384.

    We build the dict exactly as chat_cli does (heterogeneous: float + list[str]) and
    verify it can bind to `chat_ui_stream(message, session_id, **kw)`
    without TypeError.

    Pre-fix passes (client signature already accepts keyword-only). Post-fix Dev#2
    only annotates `_stream_kwargs: dict[str, Any]` — the client signature does not
    change, the bind continues to pass.
    """
    from core.cli.utils.api_client import NexeAPIClient

    _stream_kwargs: dict = {}
    _stream_kwargs["rag_threshold"] = 0.5
    _stream_kwargs["rag_collections"] = ["kb_a", "kb_b"]
    assert _stream_kwargs == {
        "rag_threshold": 0.5,
        "rag_collections": ["kb_a", "kb_b"],
    }

    sig = inspect.signature(NexeAPIClient.chat_ui_stream)
    bound = sig.bind(
        self=object(),
        message="hello",
        session_id="sess-1",
        **_stream_kwargs,
    )
    bound.apply_defaults()
    assert bound.arguments["rag_threshold"] == 0.5
    assert bound.arguments["rag_collections"] == ["kb_a", "kb_b"]
