"""Tests for plugins/ollama_module/core/chat.py — coverage gaps."""
from unittest.mock import MagicMock


class TestCanThink:
    def test_qwen3_can_think(self):
        from plugins.ollama_module.core.chat import can_think
        assert can_think("qwen3:latest") is True

    def test_qwen3_5_can_think(self):
        from plugins.ollama_module.core.chat import can_think
        assert can_think("qwen3.5:122b-a10b") is True

    def test_deepseek_r1_can_think(self):
        from plugins.ollama_module.core.chat import can_think
        assert can_think("deepseek-r1:32b") is True

    def test_gemma4_can_think(self):
        from plugins.ollama_module.core.chat import can_think
        assert can_think("gemma4:e4b") is True

    def test_llama3_cannot_think(self):
        from plugins.ollama_module.core.chat import can_think
        assert can_think("llama3.1:8b") is False

    def test_mistral_cannot_think(self):
        from plugins.ollama_module.core.chat import can_think
        assert can_think("mistral:7b") is False

    def test_with_namespace(self):
        from plugins.ollama_module.core.chat import can_think
        assert can_think("library/qwen3:8b") is True


class TestOllamaChatInit:
    def test_init(self):
        from plugins.ollama_module.core.chat import OllamaChat
        mock_client = MagicMock()
        mock_client.base_url = "http://localhost:11434"
        chat = OllamaChat(mock_client)
        assert chat.base_url == "http://localhost:11434"


class TestBuildPayload:
    def test_basic_payload(self):
        from plugins.ollama_module.core.chat import OllamaChat
        mock_client = MagicMock()
        mock_client.base_url = "http://localhost:11434"
        chat = OllamaChat(mock_client)
        payload = chat._build_payload("llama3.1:8b", [{"role": "user", "content": "hi"}], stream=True)
        assert payload["model"] == "llama3.1:8b"
        assert payload["stream"] is True
        assert "stop" in payload

    def test_payload_with_images(self):
        from plugins.ollama_module.core.chat import OllamaChat
        mock_client = MagicMock()
        mock_client.base_url = "http://localhost:11434"
        chat = OllamaChat(mock_client)
        payload = chat._build_payload(
            "llava:7b",
            [{"role": "user", "content": "describe this"}],
            stream=False,
            images=["base64data"],
        )
        last_user = [m for m in payload["messages"] if m["role"] == "user"][-1]
        assert "images" in last_user

    def test_payload_thinking_enabled_capable_model(self):
        from plugins.ollama_module.core.chat import OllamaChat
        mock_client = MagicMock()
        chat = OllamaChat(mock_client)
        payload = chat._build_payload("qwen3:8b", [{"role": "user", "content": "hi"}], stream=True, thinking_enabled=True)
        assert payload["think"] is True

    def test_payload_thinking_enabled_incapable_model(self):
        from plugins.ollama_module.core.chat import OllamaChat
        mock_client = MagicMock()
        chat = OllamaChat(mock_client)
        payload = chat._build_payload("llama3.1:8b", [{"role": "user", "content": "hi"}], stream=True, thinking_enabled=True)
        assert payload["think"] is False
