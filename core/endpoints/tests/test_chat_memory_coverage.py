"""Tests for core/endpoints/chat_memory.py — coverage gaps."""


class TestChatMemoryModule:
    def test_module_imports(self):
        from core.endpoints.chat_memory import _save_conversation_to_memory
        assert callable(_save_conversation_to_memory)
