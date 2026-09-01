"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/plugins/mlx_module/test_f984_thinking_starvation.py
Description: #984 — when the token ceiling lands inside the reasoning, the turn
    carries no answer at all: a paragraph cut mid-sentence, and no Continue
    either (a VLM-capable model disables it). Measured on Qwen3.5-9B at the
    2048 default. Raising the budget does not fix it — the same model burns
    8192 the same way. The engine retries once with thinking off, which is the
    one thing measured to answer.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from plugins.mlx_module.core.chat import MLXChatNode


_starved = MLXChatNode._answer_starved_by_thinking


class TestStarvationSignature:
    def test_ceiling_inside_an_unclosed_think_block_is_starvation(self):
        """The measured shape: opened, never closed, cut by the ceiling."""
        text = "<think>\nThe user is asking me to solve a math problem. Let me brea"
        assert _starved(text, "length", True) is True

    def test_a_closed_block_is_not_starvation(self):
        """The answer began, so the turn was cut while ANSWERING.

        That case is what Continue exists for; retrying would throw the
        started answer away.
        """
        text = "<think>reasoning</think>\nThe answer is 391 because 17*20 + 17*3"
        assert _starved(text, "length", True) is False

    def test_a_natural_stop_is_never_starvation(self):
        """No ceiling, no starvation — however the turn ended inside think."""
        assert _starved("<think>still open", "stop", True) is False
        assert _starved("<think>still open", None, True) is False

    def test_plain_text_cut_by_the_ceiling_is_not_starvation(self):
        """A non-thinking model hitting the ceiling must not trigger a retry."""
        text = "Un vector d'embeddings es una representacio numerica, en"
        assert _starved(text, "length", True) is False

    def test_an_empty_turn_is_not_starvation(self):
        assert _starved("", "length", True) is False


def test_starvation_needs_thinking_to_have_been_on():
    """With reasoning off, an unclosed <think> is the model's own output —
    not the engine starving the answer, and not something a retry can fix."""
    text = "<think>\nreasoning that was never closed"
    assert _starved(text, "length", False) is False


class TestTemplatePreOpenedBlock:
    """Qwen-family templates inject <think> into the PROMPT, so the model's own
    output carries no opener — only a closer, if it gets that far. Verified
    against the real Qwen3.5-9B template: the prompt ends `assistant\\n<think>\\n`.

    Without the flag these turns are indistinguishable from a plain answer cut
    mid-sentence, and the text path never retries. The VLM path only worked by
    accident, because its runner prepends a synthetic opener.
    """

    def test_untagged_reasoning_is_starvation_when_the_prompt_opened_the_block(self):
        text = "The user is asking me to solve a math problem. Let me brea"
        assert _starved(text, "length", True, True) is True

    def test_the_same_text_is_not_starvation_when_nothing_opened_a_block(self):
        """A model that never reasons, cut mid-answer: Continue's case."""
        text = "The user is asking me to solve a math problem. Let me brea"
        assert _starved(text, "length", True, False) is False

    def test_a_closer_still_wins_over_the_prompt_flag(self):
        """The block opened in the prompt and closed in the output: answered."""
        text = "reasoning</think>\nReben 5, 11 i 31 caramels."
        assert _starved(text, "length", True, True) is False
