"""The VLM prefill chunk size must be explicit, not mlx_vlm's 2048 default.

Measured on Qwen3.5-4B-MLX-4bit (the 8 GB tier model), peak via
mx.get_peak_memory(), prompt ~8.0k tokens:

    2048 (library default) -> 5.15 GB / 5.22 s
     512 (our default)     -> 4.06 GB / 5.27 s
     128                   -> 3.66 GB / 6.07 s
    None (no chunking)     -> 12.43 GB / 6.51 s

Hence: 512 by default (memory win, no latency cost) and `default` must mean
"leave the library alone", never "pass None" — passing None disables chunking
and triples peak memory on long prompts.
"""

import pytest

from plugins.mlx_module.core.chat import _prefill_step_kwargs


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("NEXE_MLX_PREFILL_STEP", raising=False)


def test_default_is_512():
    assert _prefill_step_kwargs() == {"prefill_step_size": 512}


def test_explicit_value_is_honoured(monkeypatch):
    monkeypatch.setenv("NEXE_MLX_PREFILL_STEP", "128")
    assert _prefill_step_kwargs() == {"prefill_step_size": 128}


def test_default_keyword_leaves_the_library_default(monkeypatch):
    """'default' must emit NO kwarg — not prefill_step_size=None."""
    monkeypatch.setenv("NEXE_MLX_PREFILL_STEP", "default")
    assert _prefill_step_kwargs() == {}


@pytest.mark.parametrize("bad", ["", "   ", "abc", "0", "-1", "none", "off", "3.5"])
def test_invalid_values_fall_back_to_512(monkeypatch, bad):
    """Notably 'none'/'off'/'0' must NOT disable chunking (12.43 GB peak)."""
    monkeypatch.setenv("NEXE_MLX_PREFILL_STEP", bad)
    assert _prefill_step_kwargs() == {"prefill_step_size": 512}


def test_never_emits_a_none_value(monkeypatch):
    """Mutation control: no input may ever produce prefill_step_size=None."""
    for value in ["", "default", "none", "off", "0", "512", "abc", "-7"]:
        monkeypatch.setenv("NEXE_MLX_PREFILL_STEP", value)
        assert _prefill_step_kwargs().get("prefill_step_size", 1) is not None


def _write_config(tmp_path, architecture):
    import json
    (tmp_path / "config.json").write_text(json.dumps({"architectures": [architecture]}))
    return str(tmp_path)


def test_qwen3_vl_keeps_the_library_default(tmp_path):
    """Chunked prefill is broken upstream for Qwen3-VL — do not make it worse.

    Verified on mlx_vlm 0.4.4: every chunked combination (2048/512/128) raises
    TypeError once the prompt exceeds the chunk size. Lowering our default to
    512 would move that crash from >2048 tokens to >512, so this architecture
    is left untouched.
    """
    path = _write_config(tmp_path, "Qwen3VLForConditionalGeneration")
    assert _prefill_step_kwargs(path) == {}


def test_catalog_architecture_still_gets_the_override(tmp_path):
    """Mutation control for the guard above: it must not swallow everything."""
    path = _write_config(tmp_path, "Qwen3_5ForConditionalGeneration")
    assert _prefill_step_kwargs(path) == {"prefill_step_size": 512}


@pytest.mark.parametrize("missing", ["", "/does/not/exist"])
def test_unreadable_model_path_does_not_disable_the_override(missing):
    assert _prefill_step_kwargs(missing) == {"prefill_step_size": 512}


@pytest.mark.parametrize(
    "env,expected",
    [(None, 512), ("128", 128), ("default", "<absent>")],
)
def test_chunk_size_actually_reaches_mlx_vlm(monkeypatch, env, expected):
    """The kwarg must arrive at the library, not just be computed.

    Without this, dropping the splat at the call site would leave every unit
    test above green while the process silently went back to the 2048 default.
    """
    mlx_vlm = pytest.importorskip("mlx_vlm")
    from unittest.mock import MagicMock, patch

    from plugins.mlx_module.core.chat import MLXChatNode

    if env is None:
        monkeypatch.delenv("NEXE_MLX_PREFILL_STEP", raising=False)
    else:
        monkeypatch.setenv("NEXE_MLX_PREFILL_STEP", env)

    captured = {}

    def _fake_stream(**kwargs):
        captured.update(kwargs)
        chunk = MagicMock()
        chunk.text = "ok"
        chunk.prompt_tokens = 10
        chunk.generation_tokens = 2
        yield chunk

    config = MagicMock()
    config.model_path = "/nonexistent"
    config.max_tokens = 32
    config.max_kv_size = 4096
    node = MLXChatNode(config=config)
    try:
        with patch.object(mlx_vlm, "stream_generate", _fake_stream):
            node._run_vlm_streaming(
                MagicMock(), MagicMock(), "hi", None, 8, lambda _t: None
            )
    finally:
        MLXChatNode._model = None

    if expected == "<absent>":
        assert "prefill_step_size" not in captured
    else:
        assert captured.get("prefill_step_size") == expected
