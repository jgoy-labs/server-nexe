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
