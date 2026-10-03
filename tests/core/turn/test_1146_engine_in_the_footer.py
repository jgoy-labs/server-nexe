"""#1146 — the footer names the engine that answered (Jordi, 03/10: «posa'm el
motor al peu»). It named only the model; a fallback (row 7 of the C4 sheet:
Ollama with a model that does not exist → MLX answers) could only be guessed
from the model's name. The web door sends `[ENGINE:…]` when an engine claims
the turn — a fallback's is the last the client reads, as with `[MODEL:]` — and
keeps it in the message's stats for the footer a reload paints."""
from tests.core.turn.test_1035_fallback_keeps_its_model import SERVED, _Mlx, _Ollama


def _engines(ctx) -> list:
    import re
    return re.findall(r"\x00\[ENGINE:([^\]]*)\]\x00", "".join(c for c in ctx.lab_wire_chunks if isinstance(c, str)))


async def test_the_engine_that_answers_is_on_the_wire_and_in_the_stats(turn_lab, app_state, session_manager):
    app_state.modules = {"mlx_module": _Mlx()}
    ctx = await turn_lab.ui(streaming=True, session_id="e1146-a", message="hola",
                            body_extra={"backend": "mlx", "model": SERVED})
    assert _engines(ctx) == ["mlx"]
    answer = [m for m in session_manager.get_session("e1146-a").messages if m["role"] == "assistant"][-1]
    assert answer["stats"]["engine"] == "mlx" and answer["stats"]["model"] == SERVED


async def test_a_fallback_sends_its_own_engine_last(turn_lab, app_state, session_manager):
    """Row 7: Ollama fails before its first byte, MLX answers."""
    app_state.modules = {"ollama_module": _Ollama(exc=RuntimeError("Ollama model not found: x")), "mlx_module": _Mlx()}
    ctx = await turn_lab.ui(streaming=True, session_id="e1146-b", message="hola",
                            body_extra={"backend": "ollama", "model": "model-que-no-existeix"})
    assert _engines(ctx)[-1] == "mlx", _engines(ctx)
    answer = [m for m in session_manager.get_session("e1146-b").messages if m["role"] == "assistant"][-1]
    assert answer["stats"]["engine"] == "mlx"


def test_the_cli_line_names_the_engine_too():
    from core.cli.chat_cli import _format_stats_line, _process_metadata_chunk
    state = {"model_name": None, "engine_name": None}
    _process_metadata_chunk({"MODEL": "Qwen3.5-9B-MLX-4bit", "ENGINE": "mlx"}, state)
    assert state["engine_name"] == "mlx"
    line = _format_stats_line(2.0, 400, state["model_name"], engine_name=state["engine_name"])
    assert "Qwen3.5-9B-MLX-4bit · MLX" in line
    assert "·" not in _format_stats_line(2.0, 400, "qwen3.5:9b").split("qwen3.5:9b")[1][:3]
