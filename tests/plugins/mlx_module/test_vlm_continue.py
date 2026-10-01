"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/plugins/mlx_module/test_vlm_continue.py
Description: C4.6-a-vlm — the MLX vision path (mlx_vlm) can resume a cut
             answer: the prompt is the one the answer was generated from plus
             the raw text generated (exact prefix by construction), a "cut"
             excludes an answer that ended on the ceiling, a VLM is
             continuable and says so.

The real-template tests read the chat templates of the local models (no
weights are loaded) and skip when a model is not on this machine.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("mlx_vlm", reason="mlx-vlm Apple-Silicon-only, absent al CI Linux")

from plugins.mlx_module.core.vlm_runner import (  # noqa: E402
    MLXVisionRunner,
    _eos_token_ids,
    _prompt_has_open_think_prefix,
    _without_echoed_opener,
)

TAIL = "Barcelona és una ciutat antiga, fundada pels romans amb el nom de Barcino, que"
HISTORY = [
    {"role": "user", "content": "Hola"},
    {"role": "assistant", "content": "Hola! Com et puc ajudar?"},
    {"role": "user", "content": "Explica'm la història de Barcelona."},
]


# ── the stream's own opener is not appended twice ─────────────────────────


def test_an_opener_the_stream_echoed_is_dropped_from_the_tail():
    prompt = "<|im_start|>assistant\n<think>\n"
    assert _without_echoed_opener(prompt, "<think>\nPenso.</think>Resposta") == "Penso.</think>Resposta"


def test_a_tail_is_kept_whole_when_the_prompt_leaves_nothing_open():
    prompt = "<|im_start|>assistant\n<think>\n\n</think>\n\n"
    assert _without_echoed_opener(prompt, "<think>\nPenso.") == "<think>\nPenso."


# ── "cut" means the ceiling, not an answer that ended on it ────────────────


def _metrics(token, tokens=64, eos=frozenset({7})):
    runner = MLXVisionRunner(SimpleNamespace(config=SimpleNamespace()))
    result = SimpleNamespace(prompt_tokens=10, generation_tokens=tokens, prompt_tps=1, generation_tps=1,
                             peak_memory=0, token=token)
    return runner._extract_vlm_metrics(result, "text", 1000, max_tokens_used=64, eos_ids=eos)


def test_the_ceiling_with_a_word_last_is_a_cut():
    assert _metrics(token=3)["finish_reason"] == "length"


def test_the_ceiling_with_an_end_of_turn_last_is_not_a_cut():
    assert _metrics(token=7)["finish_reason"] is None


def test_below_the_ceiling_is_never_a_cut():
    assert _metrics(token=3, tokens=10)["finish_reason"] is None


def test_the_eos_ids_come_from_the_processors_tokenizer():
    proc = SimpleNamespace(tokenizer=SimpleNamespace(eos_token_ids=[1, 106]))
    assert _eos_token_ids(proc) == frozenset({1, 106})
    assert _eos_token_ids(SimpleNamespace(tokenizer=SimpleNamespace(eos_token_id=2))) == frozenset({2})
    assert _eos_token_ids(SimpleNamespace()) == frozenset()


# ── the module says it can ─────────────────────────────────────────────────


def test_an_initialised_mlx_module_can_continue_whatever_the_model():
    from plugins.mlx_module.module import MLXModule

    module = MLXModule.__new__(MLXModule)
    module._initialized, module._node = True, object()
    assert module.can_continue("anything") is True
    module._initialized = False
    assert module.can_continue("anything") is False


# ── the real templates: the resume prompt IS the original prompt + the tail ─

MODELS = Path.home() / "models"
# Gemma 4's processor does not load through AutoProcessor here (it asks for a
# video processor config the repo does not ship); for text-only messages its
# tokenizer carries the same chat template, which is what these measure.
REAL = [
    ("Qwen3.5-4B-4bit", "processor"),
    ("Qwen3.5-9B-MLX-4bit", "processor"),
    ("Qwen3-VL-4B-Instruct-4bit", "processor"),
    ("gemma-4-e4b-it-4bit", "tokenizer"),
    ("gemma-4-31b-8bit", "tokenizer"),  # the one continue_final_message got wrong
]


@pytest.mark.parametrize("thinking", [False, True], ids=["think-off", "think-on"])
@pytest.mark.parametrize("name,kind", REAL, ids=[n for n, _ in REAL])
def test_the_resume_prompt_is_the_original_prompt_plus_what_was_generated(name, kind, thinking):
    path = MODELS / name
    if not (path / "config.json").is_file():
        pytest.skip(f"{name} is not on this machine")
    transformers = pytest.importorskip("transformers")
    loader = transformers.AutoProcessor if kind == "processor" else transformers.AutoTokenizer
    processor = loader.from_pretrained(str(path))
    runner = MLXVisionRunner(SimpleNamespace(config=SimpleNamespace(
        model_path=str(path), max_kv_size=None, max_tokens=64)))

    original = runner._prepare_vlm_prompt(HISTORY, "Ets en Nexe.", processor, False, thinking_enabled=thinking)
    stored = ("<think>\n" + TAIL) if _prompt_has_open_think_prefix(original) else TAIL
    resumed = runner._prepare_vlm_prompt(
        HISTORY + [{"role": "assistant", "content": stored}], "Ets en Nexe.", processor, False,
        thinking_enabled=thinking, continue_final=True,
    )
    assert resumed == original + TAIL
