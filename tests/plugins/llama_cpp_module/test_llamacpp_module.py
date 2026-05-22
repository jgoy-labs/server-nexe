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
    assert module.metadata.version == "1.0.0-beta"
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


@pytest.mark.asyncio
async def test_llamacpp_module_validate_failure_returns_false_not_zombie():
    """F5.5 G10: when validate() fails (model path set but invalid/missing),
    initialize() must return False with _initialized=False + _node=None.
    No zombie state (_initialized=True + _node=None) must be created."""
    import sys

    module = LlamaCppModule()
    mock_llama_cpp = MagicMock()

    # Mock: native lib available + model_path set + validate() fails
    mock_config = MagicMock()
    mock_config.model_path = "/fake/nonexistent/model.gguf"
    mock_config.validate.return_value = False  # validate() fails on this mock instance

    with patch.dict(sys.modules, {"llama_cpp": mock_llama_cpp}), \
         patch("plugins.llama_cpp_module.module.LlamaCppConfig.from_env", return_value=mock_config):
        result = await module.initialize({})

    assert result is False, "initialize() must return False when validate() fails"
    assert module._initialized is False, "_initialized must be False (not zombie)"
    assert module._node is None, "_node must be None"
    assert module._state == "error", "_state must be 'error'"
