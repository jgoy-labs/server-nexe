"""Anti-regression for `session_id` chat_cli (, refactor).

Covers mypy findings #21, #22, #24, #26. The
mypy problem: `session_id` returned by `client.create_ui_session()` is
`Optional[str]` and is used as `str` at the 4 chat_cli call sites (lines 308,
320, 334, 384).

The dev fix (scenario) will add a guard `assert session_id is not None`
(or early-return) to chat_cli **before** the while loop. The client signature
does NOT change. This test pins two contracts:

1. `NexeAPIClient.create_ui_session` returns `Optional[str]` (the NULLABILITY
   is the source of the mypy finding — pre and post-fix the signature keeps None possible).
2. `NexeAPIClient.chat_ui_stream` and `NexeAPIClient.upload_file` declare a
   named parameter `session_id` (does not change name with the fix).

If dev inadvertently touches the client signature (out-of-scope scenario),
this test fails — *teeth* against collateral refactor.

CEC: `inspect.signature` only. No real client invocation.
"""

from __future__ import annotations

import inspect
import typing


def test_create_ui_session_returns_optional_str() -> None:
    """Pins that `create_ui_session` continues to return `Optional[str]`.

    If dev does premature narrowing to `str` here (instead of doing it in chat_cli),
    the contract with all calling code breaks.
    """
    from core.cli.utils.api_client import NexeAPIClient

    sig = inspect.signature(NexeAPIClient.create_ui_session)
    return_ann = sig.return_annotation
    origin = typing.get_origin(return_ann)
    args = typing.get_args(return_ann)
    is_optional_str = (
        origin is typing.Union
        and str in args
        and type(None) in args
    )
    assert is_optional_str, (
        f"NexeAPIClient.create_ui_session return annotation = {return_ann!r}, "
        f"expected Optional[str] / Union[str, None]. The mypy finding #21/#22/#24/#26 "
        f"depends on this nullability — premature narrowing would break the future "
        f"guard in chat_cli."
    )


def test_upload_file_has_session_id_parameter() -> None:
    """Pins named parameter `session_id` in `upload_file` (cf. chat_cli.py:308 #21)."""
    from core.cli.utils.api_client import NexeAPIClient

    sig = inspect.signature(NexeAPIClient.upload_file)
    assert "session_id" in sig.parameters, (
        "NexeAPIClient.upload_file has lost `session_id` — breaks cluster #21."
    )


def test_chat_ui_stream_has_session_id_parameter() -> None:
    """Pins named parameter `session_id` in `chat_ui_stream` (cf.
    chat_cli.py:320,334,384 #22,#24,#26)."""
    from core.cli.utils.api_client import NexeAPIClient

    sig = inspect.signature(NexeAPIClient.chat_ui_stream)
    assert "session_id" in sig.parameters, (
        "NexeAPIClient.chat_ui_stream has lost `session_id` — "
        "breaks cluster #22/#24/#26."
    )
