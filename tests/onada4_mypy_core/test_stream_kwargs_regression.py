"""Anti-regressió cluster `_stream_kwargs` chat_cli (Onada 4.1, BUS Dev#1bis).

Cobreix els findings mypy #20, #23, #25, #27 (`01-classificacio.md`). Mypy
infereix `_stream_kwargs: dict[str, float]` per la primera assignació
(`rag_threshold = float`) i flagueja la segona (`rag_collections = list[str]`).
El fix Dev#2 (Cluster 5) anota explícitament `_stream_kwargs: dict[str, Any] = {}`.

L'únic comportament observable runtime és el desempaquetament `**_stream_kwargs`
sobre `client.chat_ui_stream(...)`. Aquest test pina:

1. `NexeAPIClient.chat_ui_stream` accepta `rag_threshold` (Optional[float]) i
   `rag_collections` (Optional[list]) com a kwargs (firma estable, no canvia
   amb el fix de Dev#2).
2. Un dict heterogeni `{'rag_threshold': 0.5, 'rag_collections': [...]}` es
   pot bind a aquesta signatura sense TypeError — exactament el patró
   `**_stream_kwargs` del chat_cli.

Si Dev#2 inadvertidament toca la firma del client (out-of-scope), aquest test
salta — *teeth* contra refactor col·lateral.

CEC: només `inspect.signature` + `Signature.bind`. Cap invocació real.
"""

from __future__ import annotations

import inspect


def test_chat_ui_stream_accepts_rag_kwargs() -> None:
    """Pina firma: `chat_ui_stream` declara `rag_threshold` i `rag_collections`."""
    from core.cli.utils.api_client import NexeAPIClient

    sig = inspect.signature(NexeAPIClient.chat_ui_stream)
    params = sig.parameters
    assert "rag_threshold" in params, (
        "NexeAPIClient.chat_ui_stream ha perdut `rag_threshold` — "
        "trenca cluster _stream_kwargs."
    )
    assert "rag_collections" in params, (
        "NexeAPIClient.chat_ui_stream ha perdut `rag_collections` — "
        "trenca cluster _stream_kwargs."
    )


def test_stream_kwargs_unpack_pattern_binds() -> None:
    """Pina contracte d'invocació: el patró exacte de chat_cli.py:259-263 +
    320/334/384.

    Construïm el dict tal i com fa chat_cli (heterogeni: float + list[str]) i
    verifiquem que es pot bind a `chat_ui_stream(message, session_id, **kw)`
    sense TypeError.

    Pre-fix passa (firma del client ja accepta keyword-only). Post-fix Dev#2
    només anota `_stream_kwargs: dict[str, Any]` — la signatura del client no
    canvia, el bind continua passant.
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
