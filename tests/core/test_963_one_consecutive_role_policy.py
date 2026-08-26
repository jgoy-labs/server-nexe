"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/core/test_963_one_consecutive_role_policy.py
Description: #963 — the repo answered "what happens to consecutive same-role
            messages?" twice, differently: session_manager DISCARDED the older
            (MC-116) and the MLX engine MERGED it. They never collided only
            because they sit in different layers. The finding asked for an
            anchoring test comparing the two, because none existed. This is it.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
import pytest

from core.chat_history import merge_consecutive_same_role


class TestTheCanonicalPolicy:
    def test_consecutive_same_role_merges_and_loses_nothing(self):
        out = merge_consecutive_same_role([
            {"role": "user", "content": "a"},
            {"role": "user", "content": "b"},
            {"role": "assistant", "content": "c"},
        ])
        assert out == [
            {"role": "user", "content": "a\n\nb"},
            {"role": "assistant", "content": "c"},
        ], "the measurement from the finding: 'a' must not disappear"

    def test_normal_alternation_is_untouched(self):
        msgs = [
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "q2"},
        ]
        assert merge_consecutive_same_role(msgs) == msgs

    def test_the_input_is_never_mutated(self):
        """session_manager passes its live history in — mutating it would
        corrupt the stored conversation, not just the prompt."""
        original = [
            {"role": "user", "content": "a"},
            {"role": "user", "content": "b"},
        ]
        snapshot = [dict(m) for m in original]
        merge_consecutive_same_role(original)
        assert original == snapshot

    @pytest.mark.parametrize("messages", [[], [{"role": "user", "content": "solo"}]])
    def test_degenerate_inputs(self, messages):
        assert merge_consecutive_same_role(messages) == messages

    def test_malformed_entries_do_not_raise(self):
        """A missing role/content must not take the chat down: both default to
        role 'user', so they merge like any other consecutive pair."""
        assert merge_consecutive_same_role([{}, {}]) == [{"role": "user", "content": "\n\n"}]


class TestBothLayersAgree:
    """The anchor the finding asked for: one policy, two call sites."""

    def test_session_history_and_the_mlx_engine_produce_the_same_turns(self):
        from plugins.mlx_module.core.generate_helpers import _merge_same_role
        from plugins.web_ui_module.core.session_manager import ChatSession

        s = ChatSession()
        s.add_message("user", "a")
        s.add_message("user", "b")
        s.add_message("assistant", "c")

        from_session = s.get_context_messages()
        from_engine = _merge_same_role(s.get_history())

        assert from_session == from_engine, (
            "the two layers must not answer the same question differently again"
        )

    def test_the_engine_delegates_instead_of_reimplementing(self, monkeypatch):
        """Behaviour equality is not enough — two identical copies also pass it.
        Swap the canonical function and the engine must follow; if someone
        re-inlines the merge loop, it won't."""
        from plugins.mlx_module.core import generate_helpers
        from plugins.web_ui_module.core.session_manager import ChatSession

        sentinel = [{"role": "user", "content": "SENTINEL"}]
        monkeypatch.setattr(
            generate_helpers, "merge_consecutive_same_role", lambda m: sentinel
        )
        assert generate_helpers._merge_same_role([{"role": "user", "content": "x"}]) is sentinel

        import plugins.web_ui_module.core.session_manager as sm

        monkeypatch.setattr(sm, "merge_consecutive_same_role", lambda m: sentinel)
        assert ChatSession().get_context_messages() is sentinel
