"""Anti-regression for `user_msg` (, refactor).

Covers mypy findings #49, #50, #51, #58 and propagated #52-#57, #60, #61
. Pins the **signature contract** of the 4 functions
in the cluster: the `user_msg` parameter must accept `None` as the default.

The dev fix will change the annotation `user_msg: str = None` to
`user_msg: Optional[str] = None` (PEP 484). The default value (`None`)
*does not change*, only the static annotation. This test pins this runtime
contract: pre-fix passes (default is already None) and post-fix continues to pass.

If dev inadvertently changes the default value (e.g. `user_msg: Optional[str] = ""`)
or renames the parameter, this test fails — *teeth* against inadvertent refactor.

CEC: signature + invocation-binding via `inspect.Signature.bind` only. The
function bodies are NOT executed (the coroutines are created and closed without awaiting).
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
        f"{module_path}.{func_name} has lost the `user_msg` parameter — "
        f"breaks cluster contract #49/#50/#51/#58."
    )
    param = sig.parameters["user_msg"]
    assert param.default is None, (
        f"{module_path}.{func_name}.user_msg.default = {param.default!r}, "
        f"expected None. The fix must keep the default at None "
        f"and only change the annotation to Optional[str]."
    )


def test_forward_to_ollama_binds_user_msg_none() -> None:
    """Pins that the signature `_forward_to_ollama(messages, request, app_state, user_msg=None)`
    accepts `user_msg=None` without a binding TypeError.

    Creates the coroutine but closes it before executing the body (CEC).
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
