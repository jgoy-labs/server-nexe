"""Anti-regressió cluster `user_msg` (Onada 4.1, BUS Dev#1bis).

Cobreix els findings mypy #49, #50, #51, #58 i propagats #52-#57, #60, #61
(`01-classificacio.md`). Pina el **contracte de signatura** de les 4 funcions
del cluster: el paràmetre `user_msg` ha d'acceptar `None` com a default.

El fix Dev#2 canviarà l'anotació `user_msg: str = None` per
`user_msg: Optional[str] = None` (PEP 484). El default value (`None`)
*no canvia*, només l'anotació estàtica. Aquest test pina aquest contracte
runtime: pre-fix passa (default ja és None) i post-fix continua passant.

Si Dev#2 inadvertidament canvia el default value (e.g. `user_msg: Optional[str] = ""`)
o reanomena el paràmetre, aquest test salta — *teeth* contra refactor inadvertit.

CEC: només firma + invocació-binding via `inspect.Signature.bind`. NO s'executa
el cos de les funcions (les coroutines es creen i tanquen sense awaitar).
"""

from __future__ import annotations

import inspect
from unittest.mock import MagicMock

import pytest


CLUSTER_TARGETS = [
    ("core.endpoints.chat_engines.ollama", "_forward_to_ollama"),
    ("core.endpoints.chat_engines.ollama", "_ollama_stream_generator"),
    ("core.endpoints.chat_engines.mlx", "_mlx_stream_generator"),
    ("core.endpoints.chat_engines.llama_cpp", "_llama_cpp_stream_generator"),
]


@pytest.mark.parametrize("module_path,func_name", CLUSTER_TARGETS)
def test_user_msg_default_is_none(module_path: str, func_name: str) -> None:
    module = __import__(module_path, fromlist=[func_name])
    func = getattr(module, func_name)
    sig = inspect.signature(func)
    assert "user_msg" in sig.parameters, (
        f"{module_path}.{func_name} ha perdut el paràmetre `user_msg` — "
        f"trenca contracte cluster #49/#50/#51/#58."
    )
    param = sig.parameters["user_msg"]
    assert param.default is None, (
        f"{module_path}.{func_name}.user_msg.default = {param.default!r}, "
        f"esperat None. El fix Onada 4.1 ha de mantenir el default a None "
        f"i només canviar l'anotació a Optional[str]."
    )


def test_forward_to_ollama_binds_user_msg_none() -> None:
    """Pina que la firma `_forward_to_ollama(messages, request, app_state, user_msg=None)`
    accepta `user_msg=None` sense TypeError de binding.

    Crea la coroutine però la tanca abans d'executar el cos (CEC).
    """
    from core.endpoints.chat_engines.ollama import _forward_to_ollama

    sig = inspect.signature(_forward_to_ollama)
    bound = sig.bind(
        messages=[{"role": "user", "content": "x"}],
        request=MagicMock(name="ChatCompletionRequest"),
        app_state=None,
        user_msg=None,
    )
    bound.apply_defaults()
    assert bound.arguments["user_msg"] is None

    coro = _forward_to_ollama(
        messages=[{"role": "user", "content": "x"}],
        request=MagicMock(name="ChatCompletionRequest"),
        app_state=None,
        user_msg=None,
    )
    try:
        import asyncio

        assert asyncio.iscoroutine(coro)
    finally:
        coro.close()
