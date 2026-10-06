"""#1141: an error before the engine answers is said as what it is.

The `engine` step switches the engine to the model the browser selected. When
that switch fails with an error the cascade policy treats as final (FD-S4: a
model the engine does not have is a 404 "not found", a bad request a 400, an
unreachable backend a 503), the step used to turn it into the generic
"Error: an internal error…" answer with a 200 that is not even stored. The
cascade at `generate` has always raised these as their HTTP answer; the step
that precedes it now does the same, through the same `raise_if_terminal`.
Anything the policy would hand to the next engine stays the generic answer.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

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
        (ValueError("Model 'Qwen3.5-35B' not found: no MLX model (config.json)"), 404, "not found"),
        (ValueError("model name has a path separator"), 400, "path separator"),
        (ConnectionError("refused"), 503, "mlx"),  # the detail names the engine
        (TimeoutError("slow"), 504, "mlx"),
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
    assert needle in raised.value.detail


@pytest.mark.parametrize("streaming", [True, False])
async def test_an_error_the_cascade_would_retry_stays_the_generic_answer(turn_lab, app_state, streaming):
    """Not every failure is final: a driver error is not a verdict on the
    request, so the step keeps its generic answer for it (and raises nothing)."""
    app_state.modules = {"mlx_module": _FailingSwitch(RuntimeError("metal driver"))}
    ctx = await turn_lab.ui(streaming=streaming, session_id=f"r1141-generic-{int(streaming)}", message="hola",
                            body_extra={"backend": "mlx", "model": "Qwen3.5-9B-MLX-4bit"})
    assert ctx.outcomes["engine"] == "short_circuit"
    assert ctx.response == INTERNAL_ERROR_TEXT
