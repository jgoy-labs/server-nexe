"""
Tests for plugins/mlx_module/module.py - targeting uncovered lines.
Lines: 49 (already initialized), 63-65 (config invalid), 72-74 (init exception),
       81 (get_info endpoint), 85-96 (chat endpoint), 109-116 (chat method),
       119-130 (health_check), 134-136 (shutdown), 139 (get_info).
"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from plugins.mlx_module.module import MLXModule
from core.loader.protocol import HealthStatus


@pytest.mark.asyncio
async def test_initialize_already_initialized():
    """Line 49: returns True immediately if already initialized."""
    module = MLXModule()
    module._initialized = True
    result = await module.initialize({})
    assert result is True


@pytest.mark.asyncio
async def test_initialize_config_invalid():
    """Lines 63-65: config.validate() returns False."""
    mock_config = MagicMock()
    mock_config.validate.return_value = False

    with patch("plugins.mlx_module.module.MLXConfig.is_metal_available", return_value=True), \
         patch("plugins.mlx_module.module.MLXConfig.from_env", return_value=mock_config):
        module = MLXModule()
        result = await module.initialize({})
        assert result is False
        assert module._initialized is False


@pytest.mark.asyncio
async def test_initialize_exception():
    """Lines 72-74: exception during initialization."""
    with patch("plugins.mlx_module.module.MLXConfig.is_metal_available", return_value=True), \
         patch("plugins.mlx_module.module.MLXConfig.from_env", side_effect=Exception("config error")):
        module = MLXModule()
        result = await module.initialize({})
        assert result is False


@pytest.mark.asyncio
async def test_chat_not_initialized_no_node():
    """Lines 106-107: chat when not initialized or no node."""
    module = MLXModule()
    module._initialized = True
    module._node = None
    with pytest.raises(RuntimeError, match="not initialized"):
        await module.chat([{"role": "user", "content": "hi"}])


@pytest.mark.asyncio
async def test_chat_calls_node_execute():
    """Lines 109-116: chat delegates to node.execute()."""
    module = MLXModule()
    module._initialized = True
    mock_node = MagicMock()
    mock_node.execute = AsyncMock(return_value={"content": "hello"})
    module._node = mock_node

    result = await module.chat(
        [{"role": "user", "content": "hi"}],
        system="Be helpful",
        session_id="sess-1",
        stream_callback=None
    )
    assert result == {"content": "hello"}
    mock_node.execute.assert_called_once()


@pytest.mark.asyncio
async def test_health_check_not_initialized():
    """Lines 119-120: health check when not initialized."""
    module = MLXModule()
    result = await module.health_check()
    assert result.status == HealthStatus.UNKNOWN
    assert "not initialized" in result.message.lower()


@pytest.mark.asyncio
async def test_health_check_healthy():
    """Lines 122-128: health check with working node."""
    module = MLXModule()
    module._initialized = True
    mock_node = MagicMock()
    mock_node.get_pool_stats.return_value = {"active_sessions": 1}
    module._node = mock_node

    result = await module.health_check()
    assert result.status == HealthStatus.HEALTHY


@pytest.mark.asyncio
async def test_health_check_exception():
    """Lines 129-130: health check when node raises exception."""
    module = MLXModule()
    module._initialized = True
    mock_node = MagicMock()
    mock_node.get_pool_stats.side_effect = Exception("pool error")
    module._node = mock_node

    result = await module.health_check()
    assert result.status == HealthStatus.UNHEALTHY


@pytest.mark.asyncio
async def test_shutdown_with_node():
    """Lines 134-136: shutdown resets model."""
    module = MLXModule()
    module._initialized = True
    mock_node = MagicMock()
    module._node = mock_node

    await module.shutdown()
    mock_node.reset_model.assert_called_once()
    assert module._initialized is False


@pytest.mark.asyncio
async def test_shutdown_without_node():
    """Line 134: shutdown when node is None."""
    module = MLXModule()
    module._initialized = True
    module._node = None

    await module.shutdown()
    assert module._initialized is False


def test_get_info_initialized():
    """Line 139: get_info with initialized node."""
    module = MLXModule()
    module._initialized = True
    mock_node = MagicMock()
    mock_node.get_pool_stats.return_value = {"sessions": 2}
    module._node = mock_node

    info = module.get_info()
    assert info["name"] == "mlx_module"
    assert info["initialized"] is True
    assert info["cache_stats"] == {"sessions": 2}


def test_get_info_not_initialized():
    """Line 139: get_info without node."""
    module = MLXModule()
    info = module.get_info()
    assert info["initialized"] is False
    assert info["cache_stats"] == {}


def test_chat_endpoint_not_initialized():
    """Lines 85-86: chat endpoint raises 503 when not initialized."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    module = MLXModule()
    module._init_router()

    app = FastAPI()
    app.include_router(module.get_router(), prefix="/mlx")

    client = TestClient(app, raise_server_exceptions=False)
    r = client.post("/mlx/chat", json={"messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 503


def test_chat_endpoint_success():
    """Lines 88-94: chat endpoint calls module.chat and returns result."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    module = MLXModule()
    module._initialized = True
    mock_node = MagicMock()
    mock_node.execute = AsyncMock(return_value={"content": "response"})
    module._node = mock_node
    module._init_router()

    app = FastAPI()
    app.include_router(module.get_router(), prefix="/mlx")

    client = TestClient(app, raise_server_exceptions=False)
    r = client.post("/mlx/chat", json={"messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 200


def test_chat_endpoint_exception():
    """Lines 95-96: chat endpoint returns 500 on exception."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    module = MLXModule()
    module._initialized = True
    mock_node = MagicMock()
    mock_node.execute = AsyncMock(side_effect=Exception("chat error"))
    module._node = mock_node
    module._init_router()

    app = FastAPI()
    app.include_router(module.get_router(), prefix="/mlx")

    client = TestClient(app, raise_server_exceptions=False)
    r = client.post("/mlx/chat", json={"messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 500


def test_info_endpoint():
    """Line 81: info endpoint returns get_info()."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    module = MLXModule()
    module._init_router()

    app = FastAPI()
    app.include_router(module.get_router(), prefix="/mlx")

    client = TestClient(app, raise_server_exceptions=False)
    r = client.get("/mlx/info")
    assert r.status_code == 200
    assert r.json()["name"] == "mlx_module"
