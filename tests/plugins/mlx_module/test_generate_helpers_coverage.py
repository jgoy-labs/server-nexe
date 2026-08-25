"""Tests for plugins/mlx_module/core/generate_helpers.py — coverage gaps."""


class TestMergeSameRole:
    def test_no_merge_alternating(self):
        from plugins.mlx_module.core.generate_helpers import _merge_same_role
        msgs = [{"role": "user", "content": "A"}, {"role": "assistant", "content": "B"}]
        result = _merge_same_role(msgs)
        assert len(result) == 2

    def test_merge_consecutive_user(self):
        from plugins.mlx_module.core.generate_helpers import _merge_same_role
        msgs = [{"role": "user", "content": "A"}, {"role": "user", "content": "B"}]
        result = _merge_same_role(msgs)
        assert len(result) == 1
        assert "A" in result[0]["content"]
        assert "B" in result[0]["content"]

    def test_empty_list(self):
        from plugins.mlx_module.core.generate_helpers import _merge_same_role
        assert _merge_same_role([]) == []


class TestEnsureStartsWithUser:
    def test_already_starts_with_user(self):
        from plugins.mlx_module.core.generate_helpers import _ensure_starts_with_user
        msgs = [{"role": "user", "content": "hi"}]
        result = _ensure_starts_with_user(msgs)
        assert result[0]["role"] == "user"

    def test_starts_with_assistant_prepends(self):
        from plugins.mlx_module.core.generate_helpers import _ensure_starts_with_user
        msgs = [{"role": "assistant", "content": "hi"}]
        result = _ensure_starts_with_user(msgs)
        assert result[0]["role"] == "user"
        assert len(result) == 2


class TestEnforceAlternation:
    def test_already_alternating(self):
        from plugins.mlx_module.core.generate_helpers import _enforce_alternation
        msgs = [{"role": "user", "content": "A"}, {"role": "assistant", "content": "B"}]
        result = _enforce_alternation(msgs)
        assert len(result) == 2

    def test_inserts_placeholder(self):
        from plugins.mlx_module.core.generate_helpers import _enforce_alternation
        msgs = [{"role": "user", "content": "A"}, {"role": "user", "content": "B"}]
        result = _enforce_alternation(msgs)
        roles = [m["role"] for m in result]
        for i in range(len(roles) - 1):
            assert roles[i] != roles[i + 1]


class TestSanitizeMessagesForAlternation:
    def test_empty_returns_empty(self):
        from plugins.mlx_module.core.generate_helpers import sanitize_messages_for_alternation
        assert sanitize_messages_for_alternation([]) == []

    def test_filters_system_messages(self):
        from plugins.mlx_module.core.generate_helpers import sanitize_messages_for_alternation
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hey"},
        ]
        result = sanitize_messages_for_alternation(msgs)
        assert all(m["role"] != "system" for m in result)

    def test_only_system_returns_empty(self):
        from plugins.mlx_module.core.generate_helpers import sanitize_messages_for_alternation
        msgs = [{"role": "system", "content": "sys"}]
        assert sanitize_messages_for_alternation(msgs) == []

    def test_normal_conversation(self):
        from plugins.mlx_module.core.generate_helpers import sanitize_messages_for_alternation
        msgs = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi"},
            {"role": "user", "content": "How are you?"},
        ]
        result = sanitize_messages_for_alternation(msgs)
        assert len(result) >= 3
        assert result[0]["role"] == "user"


class _FakeTokenizer:
    """encode() returns one 'token' per whitespace-separated word — deterministic,
    no real model needed to test the truncation arithmetic."""
    def encode(self, text):
        return text.split()

    def apply_chat_template(self, messages, **kwargs):
        return " ".join(str(m.get("content", "")) for m in messages)


class TestTruncateMessagesToBudget:
    """#845: mlx-lm ignores max_kv_size for the models this product ships by
    default, so this is the enforcement done at the prompt level instead."""

    def test_empty_messages_returns_empty(self):
        from plugins.mlx_module.core.generate_helpers import truncate_messages_to_budget
        assert truncate_messages_to_budget("sys", [], _FakeTokenizer(), 1000, 100) == []

    def test_short_conversation_untouched(self):
        from plugins.mlx_module.core.generate_helpers import truncate_messages_to_budget
        msgs = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
        ]
        result = truncate_messages_to_budget("system prompt", msgs, _FakeTokenizer(), 1000, 100)
        assert result == msgs

    def test_long_conversation_drops_oldest_keeps_newest(self):
        from plugins.mlx_module.core.generate_helpers import truncate_messages_to_budget
        msgs = [
            {"role": "user", "content": " ".join(f"old{i}" for i in range(10))},
            {"role": "assistant", "content": " ".join(f"mid{i}" for i in range(10))},
            {"role": "user", "content": " ".join(f"new{i}" for i in range(10))},
        ]
        # margin(256) + system(1) leaves 15 words of room: fits the last
        # message (10) but not also the middle one (10 more).
        result = truncate_messages_to_budget("sys", msgs, _FakeTokenizer(), max_kv_size=256 + 1 + 15, max_tokens=0)
        assert result[-1] == msgs[-1]
        assert msgs[0] not in result
        assert len(result) < len(msgs)

    def test_never_returns_empty_even_if_last_message_exceeds_budget(self):
        from plugins.mlx_module.core.generate_helpers import truncate_messages_to_budget
        huge = {"role": "user", "content": " ".join(f"w{i}" for i in range(1000))}
        result = truncate_messages_to_budget("sys", [huge], _FakeTokenizer(), max_kv_size=300, max_tokens=0)
        assert result == [huge]

    def test_degenerate_budget_keeps_last_turn_only(self):
        from plugins.mlx_module.core.generate_helpers import truncate_messages_to_budget
        msgs = [
            {"role": "user", "content": "a"},
            {"role": "assistant", "content": "b"},
            {"role": "user", "content": "c"},
        ]
        # max_tokens alone exceeds max_kv_size -> budget <= 0.
        result = truncate_messages_to_budget("sys", msgs, _FakeTokenizer(), max_kv_size=10, max_tokens=100)
        assert result == msgs[-1:]


class TestPrepareTokensTruncation:
    """#845, integration: prepare_tokens wires truncate_messages_to_budget in
    only when max_kv_size is explicitly passed."""

    def _long_alternating_messages(self, n=20):
        return [
            {"role": "user" if i % 2 == 0 else "assistant", "content": f"turn{i} " * 50}
            for i in range(n)
        ]

    def test_max_kv_size_none_disables_truncation(self):
        from plugins.mlx_module.core.generate_helpers import prepare_tokens
        msgs = self._long_alternating_messages()
        _, _, all_messages, _ = prepare_tokens("sys", msgs, msgs, _FakeTokenizer())
        assert len(all_messages) == 1 + len(msgs)  # system + all 20, nothing dropped

    def test_max_kv_size_set_truncates_both_message_lists(self):
        from plugins.mlx_module.core.generate_helpers import prepare_tokens
        msgs = self._long_alternating_messages()
        full_tokens, _cache_lookup_tokens, all_messages, all_cache_messages = prepare_tokens(
            "sys", msgs, msgs, _FakeTokenizer(), max_kv_size=500, max_tokens=100,
        )
        assert len(all_messages) < 1 + len(msgs)
        assert len(all_cache_messages) < 1 + len(msgs)
        assert all_messages[-1] == msgs[-1]
        # full_tokens comes from _FakeTokenizer().encode() on the templated
        # (space-joined) surviving messages — bounded by the same budget.
        assert len(full_tokens) <= 500
