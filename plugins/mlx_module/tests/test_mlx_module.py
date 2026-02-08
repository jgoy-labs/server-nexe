import pytest
from unittest.mock import MagicMock, patch
from plugins.mlx_module.module import MLXModule
from core.loader.protocol import HealthStatus

@pytest.mark.asyncio
async def test_mlx_module_metadata():
    module = MLXModule()
    assert module.metadata.name == "mlx_module"
    assert module.metadata.version == "1.0.0"
    assert module.metadata.module_type == "local_llm_option"

@pytest.mark.asyncio
async def test_mlx_module_initialize_no_metal():
    # Test initialize on non-metal hardware
    with patch("plugins.mlx_module.config.MLXConfig.is_metal_available", return_value=False):
        module = MLXModule()
        success = await module.initialize({})
        # Now returns False if Metal is not supported
        assert success is False
        assert module._initialized is False

@pytest.mark.asyncio
async def test_mlx_module_chat_not_initialized():
    module = MLXModule()
    with pytest.raises(RuntimeError, match="not initialized"):
        await module.chat(messages=[{"role": "user", "content": "hola"}])

@pytest.mark.asyncio
async def test_mlx_module_get_router():
    # Mocking Metal availability to allow initialization
    with patch("plugins.mlx_module.config.MLXConfig.is_metal_available", return_value=True), \
         patch("plugins.mlx_module.module.MLXChatNode", return_value=MagicMock()):
        module = MLXModule()
        await module.initialize({})
        router = module.get_router()
        assert router is not None
        assert module.get_router_prefix() == "/mlx"
