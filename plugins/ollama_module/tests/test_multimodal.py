"""
Tests suport multimodal (imatges) a ollama_module.
Usa mocks — no requereix Ollama instal·lat.
"""

import base64
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_image_b64(size: int = 100) -> str:
    """Genera bytes ficticis codificats en base64."""
    return base64.b64encode(b"\xff\xd8\xff" + b"\x00" * size).decode()


# ── OllamaChat._build_payload ─────────────────────────────────────────────────

class TestBuildPayload:
    def _chat(self):
        from plugins.ollama_module.core.chat import OllamaChat
        client = MagicMock()
        client.base_url = "http://localhost:11434"
        return OllamaChat(client)

    def test_text_only_no_images_key(self):
        """Sense imatges, el payload NO ha de tenir la clau 'images'."""
        chat = self._chat()
        payload = chat._build_payload("llama3.2", [{"role": "user", "content": "Hola"}], stream=True)
        assert "images" not in payload

    def test_with_images_adds_key(self):
        """Amb imatges, 'images' va dins el darrer missatge user (format /api/chat)."""
        chat = self._chat()
        img = _make_image_b64()
        payload = chat._build_payload(
            "llava", [{"role": "user", "content": "Descriu"}], stream=True, images=[img]
        )
        # images han d'estar dins el missatge user, NO al top-level
        assert "images" not in payload
        assert payload["messages"][-1]["images"] == [img]

    def test_empty_images_list_not_added(self):
        """Llista buida no afegeix la clau 'images'."""
        chat = self._chat()
        payload = chat._build_payload("llava", [], stream=True, images=[])
        assert "images" not in payload


# ── OllamaChat.chat — integració amb mock httpx ──────────────────────────────

@pytest.mark.asyncio
async def test_chat_text_only_no_regression():
    """Text-only segueix funcionant igual (sense imatge)."""
    from plugins.ollama_module.core.chat import OllamaChat

    client = MagicMock()
    client.base_url = "http://localhost:11434"
    chat = OllamaChat(client)

    fake_response = MagicMock()
    fake_response.raise_for_status = MagicMock()
    fake_response.json.return_value = {"message": {"content": "Hola!"}, "done": True}

    mock_breaker = AsyncMock()
    mock_breaker.check_circuit.return_value = True
    mock_breaker.record_success = AsyncMock()
    mock_breaker.config.timeout_seconds = 30

    mock_httpx = MagicMock()
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=fake_response)
    mock_httpx.AsyncClient.return_value = mock_client
    mock_httpx.Timeout = MagicMock(return_value=MagicMock())

    with patch("plugins.ollama_module.module.httpx", mock_httpx), \
         patch("plugins.ollama_module.module.ollama_breaker", mock_breaker):
        results = []
        async for chunk in chat.chat("llama3.2", [{"role": "user", "content": "Hola"}], stream=False):
            results.append(chunk)

    assert results
    assert results[0]["message"]["content"] == "Hola!"


@pytest.mark.asyncio
async def test_chat_images_reach_payload():
    """Amb imatge, el payload enviat a Ollama conté 'images'."""
    from plugins.ollama_module.core.chat import OllamaChat

    client = MagicMock()
    client.base_url = "http://localhost:11434"
    chat = OllamaChat(client)

    captured_payload = {}

    fake_response = MagicMock()
    fake_response.raise_for_status = MagicMock()
    fake_response.json.return_value = {"message": {"content": "Una imatge!"}, "done": True}

    async def fake_post(url, json=None, **kwargs):
        captured_payload.update(json or {})
        return fake_response

    mock_breaker = AsyncMock()
    mock_breaker.check_circuit.return_value = True
    mock_breaker.record_success = AsyncMock()
    mock_breaker.config.timeout_seconds = 30

    mock_httpx = MagicMock()
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = fake_post
    mock_httpx.AsyncClient.return_value = mock_client
    mock_httpx.Timeout = MagicMock(return_value=MagicMock())

    img_b64 = _make_image_b64()

    with patch("plugins.ollama_module.module.httpx", mock_httpx), \
         patch("plugins.ollama_module.module.ollama_breaker", mock_breaker):
        results = []
        async for chunk in chat.chat(
            "llava",
            [{"role": "user", "content": "Descriu la foto"}],
            stream=False,
            images=[img_b64],
        ):
            results.append(chunk)

    # images han d'estar dins el darrer missatge user, NO al top-level
    assert "images" not in captured_payload
    user_msgs = [m for m in captured_payload["messages"] if m.get("role") == "user"]
    assert user_msgs[-1]["images"] == [img_b64]


# ── OllamaModule.chat — signatura ─────────────────────────────────────────────

def test_module_chat_accepts_images_param():
    """OllamaModule.chat() accepta el paràmetre images sense error."""
    import inspect
    from plugins.ollama_module.module import OllamaModule
    sig = inspect.signature(OllamaModule.chat)
    assert "images" in sig.parameters
