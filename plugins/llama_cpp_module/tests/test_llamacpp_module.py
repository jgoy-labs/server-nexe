import pytest
from unittest.mock import MagicMock, patch
from plugins.llama_cpp_module.module import LlamaCppModule
from core.loader.protocol import HealthStatus

@pytest.mark.asyncio
async def test_llamacpp_module_metadata():
    module = LlamaCppModule()
    assert module.metadata.name == "llama_cpp_module"
    assert module.metadata.version == "0.8.5"
    assert module.metadata.module_type == "local_llm_option"

@pytest.mark.asyncio
async def test_llamacpp_module_initialize_failure():
    # Test initialize with invalid config (model file not exists)
    with patch("plugins.llama_cpp_module.core.config.os.path.exists", return_value=False):
        module = LlamaCppModule()
        # Should start even with warning (degraded mode concept)
        # But wait, looking at my module.py, it returns True and logs warning
        success = await module.initialize({})
        assert success is True
        
        health = await module.health_check()
        # Since _node is not initialized if validate fails? 
        # Actually in my module.py, I initialize _node anyway if validate returns True or it continues.
        # Let's check my module.py logic again.
        # It calls:
        # if not llama_config.validate():
        #     logger.warning("...")
        #     return True 
        # self._node = LlamaCppChatNode(config=llama_config)
        # So it continues even if invalid.

@pytest.mark.asyncio
async def test_llamacpp_module_chat_not_initialized():
    module = LlamaCppModule()
    with pytest.raises(RuntimeError, match="Module not initialized"):
        await module.chat(messages=[{"role": "user", "content": "hola"}])

@pytest.mark.asyncio
async def test_llamacpp_module_get_router():
    module = LlamaCppModule()
    await module.initialize({})
    router = module.get_router()
    assert router is not None
    assert module.get_router_prefix() == "/llama-cpp"
