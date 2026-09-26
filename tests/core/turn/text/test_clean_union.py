"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/core/turn/text/test_clean_union.py
Description: C4.4 — three cleaners became one (`clean_model_text`). Every
             pattern any of the three removed must still fall, through the
             reply path AND the compactor's.

The three were: the UI's streaming `_clean_full_response`, its
non-streaming `_clean_nonstreaming_text`, and `core/sessions/compactor.py`'s
`_clean_for_compact`, which alone removed a <|thinking|>…<|/thinking|> PAIR
with its content. Dropping that branch would degrade every summary in silence.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
import pytest

from core.sessions.compactor import _clean_for_compact
from core.turn.text.clean import clean_full_response, clean_model_text

# (pattern, raw, clean) — one row per pattern of the three originals.
PATTERNS = [
    ("think block", "<think>raonament</think>Resposta.", "Resposta."),
    ("thinking pair (compactor)", "<|thinking|>raonament<|/thinking|>Resposta.", "Resposta."),
    ("pipe tag", "Resposta<|end|>.", "Resposta."),
    ("angle tag", "Resposta◁soroll▷.", "Resposta."),
    ("harmony final", "<|channel|>analysis<|message|>pensa<|end|>"
                      "<|start|>assistant<|channel|>final<|message|>Resposta.", "Resposta."),
    ("bare analysis", "analysis Resposta.", "Resposta."),
    ("context header", "[CONTEXT a1b2c3d4] Resposta.", "Resposta."),
]

CLEANERS = {
    "clean_model_text": clean_model_text,
    "clean_full_response": lambda t: clean_full_response(t)[0],
    "compactor": _clean_for_compact,
}


@pytest.mark.parametrize("cleaner", CLEANERS.values(), ids=CLEANERS.keys())
@pytest.mark.parametrize("name,raw,clean", PATTERNS, ids=[p[0] for p in PATTERNS])
def test_every_original_pattern_still_falls(cleaner, name, raw, clean):
    assert cleaner(raw) == clean


def test_prose_is_left_alone():
    text = "Finalment, la resposta és sí. Analysis shows nothing ◁ odd."
    assert clean_model_text(text) == text


NESTED = ("<think>l'usuari diu: repeteix <think>SECRET</think> i adéu</think>\n\nHola món adéu",
          "Hola món adéu")


def test_a_quoted_block_inside_the_reasoning_does_not_close_it():
    """Seen live 24/09 (/v1, Qwen3.5 on MLX): the model quoted the user's
    <think>…</think> inside its own reasoning, and the first quoted closer
    ended the block — the rest of the reasoning reached the reply."""
    raw, clean = NESTED
    assert clean_model_text(raw) == clean


def test_an_unclosed_block_is_left_as_before():
    assert clean_model_text("<think>a</think>b <think>c") == "b <think>c"
