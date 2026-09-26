"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/core/turn/text/test_1093_final_word_does_not_cut_the_reply.py
Description: The gpt-oss analysis/final cut applies only to harmony-shaped
             text. It used to fire on the word "final" anywhere, so a reply
             lost everything before "Finalment" / "final answer".

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
import pytest

from core.turn.text.clean import clean_full_response as _clean_full_response
from core.turn.text.clean import clean_model_text as _clean_nonstreaming_text


def _stream(text: str) -> str:
    return _clean_full_response(text)[0]


CLEANERS = [_stream, _clean_nonstreaming_text]

ORDINARY = [
    "Primer rega l'olivera. Finalment, posa-hi compost de closca d'ametlla.",
    "The final answer is 42, but first read the manual.",
    "Al final del dia, la resposta és sí.",
    # the word at the very start is prose too, not the harmony channel
    "Finalment, la resposta és sí.",
    "Final de la història: se'n van anar.",
    "Analysis of the logs shows the final step failed.",
]

HARMONY = [
    # raw harmony, tags stripped by the cleaner itself
    ("<|channel|>analysis<|message|>Think: the final value is 42."
     "<|end|><|start|>assistant<|channel|>final<|message|>La resposta és 42.",
     "La resposta és 42."),
    ("<|channel|>final<|message|>Només la resposta.", "Només la resposta."),
    ("analysis some stuff\nfinal The real answer is 42.", "The real answer is 42."),
    ("analysis  this is the actual answer", "this is the actual answer"),
]


@pytest.mark.parametrize("clean", CLEANERS)
@pytest.mark.parametrize("text", ORDINARY)
def test_an_ordinary_reply_is_kept_whole(clean, text):
    assert clean(text) == text


@pytest.mark.parametrize("clean", CLEANERS)
@pytest.mark.parametrize("raw,answer", HARMONY)
def test_a_harmony_reply_still_keeps_only_the_answer(clean, raw, answer):
    assert clean(raw) == answer
