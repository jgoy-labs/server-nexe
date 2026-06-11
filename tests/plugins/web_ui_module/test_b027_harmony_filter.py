"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/plugins/web_ui_module/test_b027_harmony_filter.py
Description: B027a — gpt-oss harmony reasoning leaked verbatim into the
    visible bubble. HarmonyStreamFilter must rewrite channel structure into
    <think>…</think> even when tags arrive split across stream chunks.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import pytest

from plugins.web_ui_module.core.harmony_filter import HarmonyStreamFilter


def _run(chunks):
    f = HarmonyStreamFilter()
    out = "".join(f.feed(c) for c in chunks)
    return out + f.flush()


FULL_SEQUENCE = (
    "<|channel|>analysis<|message|>I need to multiply 17 by 23.<|end|>"
    "<|start|>assistant<|channel|>final<|message|>The answer is 391."
)
EXPECTED = "<think>I need to multiply 17 by 23.</think>The answer is 391."


class TestHarmonyStreamFilter:
    def test_full_sequence_single_chunk(self):
        assert _run([FULL_SEQUENCE]) == EXPECTED

    def test_token_by_token_chunks(self):
        # MLX streams token by token — each tag arrives as its own chunk and
        # the bare 'assistant' role word between <|start|> and <|channel|>
        # must never reach the visible output.
        chunks = [
            "<|channel|>", "analysis", "<|message|>", "I need to multiply ",
            "17 by 23.", "<|end|>", "<|start|>", "assistant", "<|channel|>",
            "final", "<|message|>", "The answer ", "is 391.",
        ]
        assert _run(chunks) == "<think>I need to multiply 17 by 23.</think>The answer is 391."

    def test_tags_split_mid_chunk(self):
        chunks = [
            "<|chan", "nel|>analy", "sis<|mess", "age|>reasoning here",
            "<|e", "nd|><|start|>assist", "ant<|channel|>fin", "al<|message|>answer",
        ]
        assert _run(chunks) == "<think>reasoning here</think>answer"

    def test_plain_text_passthrough(self):
        chunks = ["Hola, ", "com va tot? ", "Resposta sense tags."]
        assert _run(chunks) == "Hola, com va tot? Resposta sense tags."

    def test_text_with_angle_brackets_passthrough(self):
        # Math like "a < b" must not be eaten by the partial-tag holdback.
        assert _run(["3 < 5 i 7 > 2"]) == "3 < 5 i 7 > 2"

    def test_flush_closes_open_thinking(self):
        # Stream cut while still in analysis — the think block must be closed
        # so downstream parsers do not leak the rest of the turn as thinking.
        f = HarmonyStreamFilter()
        out = f.feed("<|channel|>analysis<|message|>partial reasoning")
        out += f.flush()
        assert out == "<think>partial reasoning</think>"

    def test_commentary_channel_treated_as_thinking(self):
        seq = (
            "<|channel|>commentary<|message|>calling a tool<|end|>"
            "<|start|>assistant<|channel|>final<|message|>done"
        )
        assert _run([seq]) == "<think>calling a tool</think>done"

    def test_return_and_constrain_tags_stripped(self):
        seq = "<|channel|>final<|message|>resposta<|return|>"
        assert _run([seq]) == "resposta"

    def test_final_only_no_think_block(self):
        seq = "<|channel|>final<|message|>directe sense reasoning"
        assert _run([seq]) == "directe sense reasoning"

    def test_malformed_endless_channel_name_passes_through(self):
        # No <|message|> ever arrives: after the cap, bail out to passthrough
        # instead of swallowing the stream.
        long_garbage = "x" * 100
        out = _run(["<|channel|>" + long_garbage])
        assert long_garbage in out

    def test_partial_tag_tail_held_until_completed(self):
        f = HarmonyStreamFilter()
        first = f.feed("text abans <|")
        assert first == "text abans "
        second = f.feed("channel|>final<|message|>després")
        assert second == "després"
        assert f.flush() == ""

    @pytest.mark.parametrize("tag", ["<|end|>", "<|start|>assistant<|channel|>final<|message|>"])
    def test_no_visible_leak_of_structural_tags(self, tag):
        out = _run(["<|channel|>final<|message|>abans", tag, "després"])
        assert "<|" not in out
        assert "assistant" not in out
