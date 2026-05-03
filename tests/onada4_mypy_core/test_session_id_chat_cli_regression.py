"""Anti-regressió cluster `session_id` chat_cli (Onada 4.1, BUS Dev#1bis).

Cobreix els findings mypy #21, #22, #24, #26 (`01-classificacio.md`). El
problema mypy: `session_id` retornat per `client.create_ui_session()` és
`Optional[str]` i s'usa com a `str` als 4 call sites de chat_cli (línies 308,
320, 334, 384).

El fix Dev#2 (Cluster 8) afegirà un guard `assert session_id is not None`
(o early-return) al chat_cli **abans** del while loop. La firma del client
NO canvia. Aquest test pina dos contractes:

1. `NexeAPIClient.create_ui_session` retorna `Optional[str]` (la NULLABILITAT
   és font del finding mypy — pre i post-fix la firma manté None possible).
2. `NexeAPIClient.chat_ui_stream` i `NexeAPIClient.upload_file` declaren un
   paràmetre nominat `session_id` (no canvia de nom amb el fix).

Si Dev#2 inadvertidament toca la firma del client (out-of-scope cluster 8),
aquest test salta — *teeth* contra refactor col·lateral.

CEC: només `inspect.signature`. Cap invocació real del client.
"""

from __future__ import annotations

import inspect
import typing


def test_create_ui_session_returns_optional_str() -> None:
    """Pina que `create_ui_session` continua retornant `Optional[str]`.

    Si Dev#2 fa narrowing prematur a `str` aquí (en lloc de fer-lo al chat_cli),
    el contracte amb tot el codi crida-er trenca.
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
        f"esperat Optional[str] / Union[str, None]. El finding mypy #21/#22/#24/#26 "
        f"depèn d'aquesta nullabilitat — narrowing prematur trencaria el guard "
        f"futur del chat_cli."
    )


def test_upload_file_has_session_id_parameter() -> None:
    """Pina paràmetre nominat `session_id` a `upload_file` (cf. chat_cli.py:308 #21)."""
    from core.cli.utils.api_client import NexeAPIClient

    sig = inspect.signature(NexeAPIClient.upload_file)
    assert "session_id" in sig.parameters, (
        "NexeAPIClient.upload_file ha perdut `session_id` — trenca cluster #21."
    )


def test_chat_ui_stream_has_session_id_parameter() -> None:
    """Pina paràmetre nominat `session_id` a `chat_ui_stream` (cf.
    chat_cli.py:320,334,384 #22,#24,#26)."""
    from core.cli.utils.api_client import NexeAPIClient

    sig = inspect.signature(NexeAPIClient.chat_ui_stream)
    assert "session_id" in sig.parameters, (
        "NexeAPIClient.chat_ui_stream ha perdut `session_id` — "
        "trenca cluster #22/#24/#26."
    )
