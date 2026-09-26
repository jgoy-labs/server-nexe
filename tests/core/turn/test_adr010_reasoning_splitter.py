"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/core/turn/test_adr010_reasoning_splitter.py
Description: ADR-010 — the one splitter engines use to return their
             model's reasoning apart from the answer, instead of mixing it
             into the text for the core to guess at.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
import pytest

from core.turn.reasoning import ReasoningSplitter, split_text, structured_chunk
from core.turn.text.chunks import parse_chunk


@pytest.mark.parametrize("raw,kwargs,expected", [
    ("<think>raona</think>\n\nResposta.", {}, ("raona", "Resposta.")),
    ("Resposta sense raonar.", {}, ("", "Resposta sense raonar.")),
    # the chat template opened the block in the prompt (Qwen3.5 on MLX)
    ("raonament intern</think>\n\nResposta.", {"starts_inside": True}, ("raonament intern", "Resposta.")),
    # the reasoning quotes the tags (seen live 24/09)
    ("<think>repeteix <think>S</think> i prou</think>Hola", {}, ("repeteix <think>S</think> i prou", "Hola")),
    # gpt-oss harmony
    ("<|channel|>analysis<|message|>pensa<|end|><|start|>assistant<|channel|>final<|message|>Resposta.",
     {"harmony": True}, ("pensa", "Resposta.")),
    # never closed: all of it is reasoning (the #984 starved turn)
    ("<think>no acaba mai", {}, ("no acaba mai", "")),
])
def test_a_whole_reply_splits(raw, kwargs, expected):
    assert split_text(raw, **kwargs) == expected


def test_the_split_does_not_depend_on_where_the_chunks_break():
    raw = "abans <think>raona <think>q</think> més</think>\n després"
    whole = split_text(raw)
    for cut in range(1, len(raw)):
        s = ReasoningSplitter()
        t1, c1 = s.feed(raw[:cut])
        t2, c2 = s.feed(raw[cut:])
        t3, c3 = s.flush()
        assert (t1 + t2 + t3, c1 + c2 + c3) == whole


def test_a_lone_angle_bracket_is_answer():
    assert split_text("a < b i <th") == ("", "a < b i <th")


def test_the_contract_shape_is_what_the_core_already_reads():
    chunk = structured_chunk("Resposta", "raona", raw="<think>raona</think>Resposta")
    assert parse_chunk(chunk) == ("Resposta", "raona")
