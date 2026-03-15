"""
Tests for plugins/llama_cpp_module/module.py - targeting uncovered lines.
Lines: 69-73 (init exception), 80 (info endpoint), 84-95 (chat endpoint),
       108-115 (chat method), 119/123 (health_check), 133-135/138 (shutdown/get_info).
"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from plugins.llama_cpp_module.module import LlamaCppModule
from core.loader.protocol import HealthStatus


@pytest.mark.asyncio
async def test_initialize_already_initialized():
    """Line 48-49: returns True if already initialized."""
    module = LlamaCppModule()
    module._initialized = True
    result = await module.initialize({})
    assert result is True


@pytest.mark.asyncio
async def test_initialize_exception():
    """Lines 69-73: exception during initialization returns False."""
    with patch("plugins.llama_cpp_module.module.LlamaCppConfig.from_env",
               side_effect=Exception("config error")):
        module = LlamaCppModule()
        result = await module.initialize({})
        assert result is False


@pytest.mark.asyncio
async def test_chat_not_initialized_no_node():
    """Lines 105-106: chat raises RuntimeError when not initialized or no node."""
    module = LlamaCppModule()
    module._initialized = True
    module._node = None
    with pytest.raises(RuntimeError, match="not initialized"):
        await module.chat([{"role": "user", "content": "hi"}])


@pytest.mark.asyncio
async def test_chat_calls_node_execute():
    """Lines 108-115: chat delegates to node.execute()."""
    module = LlamaCppModule()
    module._initialized = True
    mock_node = MagicMock()
    mock_node.execute = AsyncMock(return_value={"content": "hello"})
    module._node = mock_node

    result = await module.chat(
        [{"role": "user", "content": "hi"}],
        system="System prompt",
        session_id="sess-1",
        stream_callback=None
    )
    assert result == {"content": "hello"}
    mock_node.execute.assert_called_once()


@pytest.mark.asyncio
async def test_health_check_not_initialized():
    """Lines 118-119: health check when not initialized."""
    module = LlamaCppModule()
    result = await module.health_check()
    assert result.status == HealthStatus.UNKNOWN


@pytest.mark.asyncio
async def test_health_check_healthy():
    """Lines 121-128: health check with working node."""
    module = LlamaCppModule()
    module._initialized = True
    mock_node = MagicMock()
    mock_node.get_pool_stats.return_value = {"active": 1}
    module._node = mock_node

    result = await module.health_check()
    assert result.status == HealthStatus.HEALTHY


@pytest.mark.asyncio
async def test_health_check_exception():
    """Lines 128-129: health check exception returns UNHEALTHY."""
    module = LlamaCppModule()
    module._initialized = True
    mock_node = MagicMock()
    mock_node.get_pool_stats.side_effect = Exception("pool broken")
    module._node = mock_node

    result = await module.health_check()
    assert result.status == HealthStatus.UNHEALTHY


@pytest.mark.asyncio
async def test_shutdown_with_node():
    """Lines 133-135: shutdown resets model."""
    module = LlamaCppModule()
    module._initialized = True
    mock_node = MagicMock()
    module._node = mock_node

    await module.shutdown()
    mock_node.reset_model.assert_called_once()
    assert module._initialized is False


@pytest.mark.asyncio
async def test_shutdown_without_node():
    """Line 133: shutdown when node is None."""
    module = LlamaCppModule()
    module._initialized = True
    module._node = None

    await module.shutdown()
    assert module._initialized is False


def test_get_info_with_node():
    """Line 138: get_info with initialized node."""
    module = LlamaCppModule()
    module._initialized = True
    mock_node = MagicMock()
    mock_node.get_pool_stats.return_value = {"sessions": 1}
    module._node = mock_node

    info = module.get_info()
    assert info["name"] == "llama_cpp_module"
    assert info["initialized"] is True
    assert info["pool_stats"] == {"sessions": 1}


def test_get_info_without_node():
    """Line 138: get_info without node."""
    module = LlamaCppModule()
    info = module.get_info()
    assert info["initialized"] is False
    assert info["pool_stats"] == {}


def test_chat_endpoint_not_initialized():
    """Lines 84-85: chat endpoint 503 when not initialized."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    module = LlamaCppModule()
    module._init_router()

    app = FastAPI()
    app.include_router(module.get_router(), prefix="/llama-cpp")

    client = TestClient(app, raise_server_exceptions=False)
    r = client.post("/llama-cpp/chat", json={"messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 503


def test_chat_endpoint_success():
    """Lines 87-93: chat endpoint returns result."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    module = LlamaCppModule()
    module._initialized = True
    mock_node = MagicMock()
    mock_node.execute = AsyncMock(return_value={"content": "response"})
    module._node = mock_node
    module._init_router()

    app = FastAPI()
    app.include_router(module.get_router(), prefix="/llama-cpp")

    client = TestClient(app, raise_server_exceptions=False)
    r = client.post("/llama-cpp/chat", json={"messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 200


def test_chat_endpoint_exception():
    """Lines 94-95: chat endpoint 500 on error."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    module = LlamaCppModule()
    module._initialized = True
    mock_node = MagicMock()
    mock_node.execute = AsyncMock(side_effect=Exception("chat error"))
    module._node = mock_node
    module._init_router()

    app = FastAPI()
    app.include_router(module.get_router(), prefix="/llama-cpp")

    client = TestClient(app, raise_server_exceptions=False)
    r = client.post("/llama-cpp/chat", json={"messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 500


def test_info_endpoint():
    """Line 80: info endpoint."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    module = LlamaCppModule()
    module._init_router()

    app = FastAPI()
    app.include_router(module.get_router(), prefix="/llama-cpp")

    client = TestClient(app, raise_server_exceptions=False)
    r = client.get("/llama-cpp/info")
    assert r.status_code == 200
    assert r.json()["name"] == "llama_cpp_module"
