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
async def test_llamacpp_module_initialize_failure():
    """T4 REFORÇAT — quan NEXE_LLAMA_CPP_MODEL apunta a un path invàlid, initialize()
    ha de retornar False i _state='error' (module.py:103-115).
    Bug tapat: el patch original (os.path.exists=False sense NEXE_LLAMA_CPP_MODEL)
    era mort perquè from_env() torna not_configured (model_path buit) → return True ABANS
    de validate(). La branca de fallida real (model_path set + validate() False → _state=error)
    quedava sense cobertura.
    Prova de mutació: canviar `self._state = "error"` per `self._state = "not_configured"` a
    module.py:113 posa aquest test VERMELL (assert _state == "error" falla).
    No requereix llama_cpp instal·lat: es mocka sys.modules['llama_cpp'] per passar el
    ImportError check (module.py:66-78) i s'usa el validate() real de LlamaCppConfig.
    """
    import sys

    module = LlamaCppModule()
    mock_llama_cpp = MagicMock()

    # We set the model to an invalid path so from_env() detects it and validate() fails
    with patch.dict(sys.modules, {"llama_cpp": mock_llama_cpp}), \
         patch.dict("os.environ", {"NEXE_LLAMA_CPP_MODEL": "/nonexistent/path/model.gguf"}):
        success = await module.initialize({})

    assert success is False, (
        "initialize() ha de retornar False quan validate() falla "
        "(model_path configurat però invàlid)"
    )
    assert module._state == "error", (
        f"_state ha de ser 'error' quan validate() falla, obtingut: {module._state!r}"
    )
    assert module._initialized is False, "_initialized ha de ser False"
    assert module._node is None, "_node ha de ser None"

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
