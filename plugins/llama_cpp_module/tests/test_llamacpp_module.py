import pytest
import importlib
from unittest.mock import MagicMock, patch
from plugins.llama_cpp_module.module import LlamaCppModule
from core.loader.protocol import HealthStatus

_llama_cpp_available = importlib.util.find_spec("llama_cpp") is not None

@pytest.mark.asyncio
async def test_llamacpp_module_metadata():
    module = LlamaCppModule()
    assert module.metadata.name == "llama_cpp_module"
    assert module.metadata.version == "0.9.9"
    assert module.metadata.module_type == "local_llm_option"

@pytest.mark.asyncio
@pytest.mark.skipif(not _llama_cpp_available, reason="llama_cpp not installed")
async def test_llamacpp_module_initialize_failure():
    with patch("plugins.llama_cpp_module.core.config.os.path.exists", return_value=False):
        module = LlamaCppModule()
        success = await module.initialize({})
        assert success is True

@pytest.mark.asyncio
async def test_llamacpp_module_chat_not_initialized():
    module = LlamaCppModule()
    with pytest.raises(RuntimeError, match="Module not initialized"):
        await module.chat(messages=[{"role": "user", "content": "hola"}])

@pytest.mark.asyncio
@pytest.mark.skipif(not _llama_cpp_available, reason="llama_cpp not installed")
async def test_llamacpp_module_get_router():
    module = LlamaCppModule()
    await module.initialize({})
    router = module.get_router()
    assert router is not None
    assert module.get_router_prefix() == "/llama-cpp"
