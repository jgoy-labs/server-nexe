"""#1141: an error before the engine answers is said as what it is.

The `engine` step switches the engine to the model the browser selected. When
that switch fails with an error the cascade policy treats as final (FD-S4: a
model the engine does not have is a 404, a bad request a 400 — said on purpose,
`ModelNotFound`/`BadRequest`), the step used to turn it into the generic
"Error: an internal error…" answer with a 200 that is not even stored. The
cascade at `generate` has always raised these as their HTTP answer; the step
that precedes it now does the same, through the same `raise_if_terminal`, with
the message nexe wrote for the user (P2-7: never raw text, never a lost message). Anything the policy would hand to the next engine — an
engine down, too slow or failing, since C4.8 N5 — stays the generic answer.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from core.turn.errors import BadRequest, ModelNotFound
from plugins.web_ui_module.api.turn_adapters import INTERNAL_ERROR_TEXT

from .test_1035_fallback_keeps_its_model import _Mlx


class _FailingSwitch(_Mlx):
    def __init__(self, exc: Exception):
        super().__init__()
        self._exc = exc

    def switch_model_by_path(self, local_path) -> bool:
        raise self._exc


@pytest.mark.parametrize("streaming", [True, False])
@pytest.mark.parametrize(
    ("exc", "status", "needle"),
    [
        (ModelNotFound("Model 'Qwen3.5-35B' not found: no MLX model (config.json)"), 404, "not found"),
        (BadRequest("model name has a path separator"), 400, "path separator"),
    ],
)
async def test_a_terminal_error_in_the_engine_step_is_its_http_answer(
    turn_lab, app_state, streaming, exc, status, needle,
):
    app_state.modules = {"mlx_module": _FailingSwitch(exc)}
    with pytest.raises(HTTPException) as raised:
        await turn_lab.ui(streaming=streaming, session_id=f"r1141-{status}-{int(streaming)}", message="hola",
                          body_extra={"backend": "mlx", "model": "Qwen3.5-35B-A3B-4bit"})
    assert raised.value.status_code == status
    assert needle in raised.value.detail, "the message written for the user arrives whole (P2-7)"


@pytest.mark.parametrize("streaming", [True, False])
@pytest.mark.parametrize("exc", [RuntimeError("metal driver"), ConnectionError("refused"), TimeoutError("slow")])
async def test_an_error_the_cascade_would_retry_stays_the_generic_answer(turn_lab, app_state, streaming, exc):
    """Not every failure is final: an engine failing, unreachable or too slow is
    not a verdict on the request (N5: the cascade would try the next engine), so
    the step, which has no next engine, keeps its generic answer (and raises nothing)."""
    app_state.modules = {"mlx_module": _FailingSwitch(exc)}
    ctx = await turn_lab.ui(streaming=streaming, session_id=f"r1141-generic-{int(streaming)}-{type(exc).__name__}", message="hola",
                            body_extra={"backend": "mlx", "model": "Qwen3.5-9B-MLX-4bit"})
    assert ctx.outcomes["engine"] == "short_circuit"
    assert ctx.response == INTERNAL_ERROR_TEXT
