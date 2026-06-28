"""B073 — el canvi de model des del web_ui ha de passar per una API pública.

Abans del fix, routes_chat._switch_{mlx,llama_cpp}_model feien cirurgia a mà
sobre atributs privats de classe d'altres plugins (MLXChatNode._model,
LlamaCppChatNode._pool/_config). Sense cap test, un refactor d'aquells motors
trencaria el canvi de model en silenci.

Aquests tests fixen el contracte públic:
  node.apply_config(new_config)  -> reset dels singletons de classe (al plugin)
  module.switch_model(new_config) -> decideix i delega a apply_config
  routes_chat._switch_*_model(engine, path) -> crida engine.switch_model(...)
i NO toca cap atribut privat de classe.
"""
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import Mock, patch

import pytest


@pytest.fixture(autouse=True)
def _reset_class_singletons():
    """Els nodes guarden _model/_pool/_config a nivell de CLASSE (compartits
    entre instàncies i tests). Restaura'ls perquè aquests tests no contaminin
    la resta del gate."""
    from plugins.mlx_module.core.chat import MLXChatNode
    from plugins.llama_cpp_module.core.chat import LlamaCppChatNode
    saved = (
        MLXChatNode._model, MLXChatNode._config, getattr(MLXChatNode, "_is_vlm", False),
        LlamaCppChatNode._pool, LlamaCppChatNode._config,
    )
    # estat net abans de cada test (no heretar singletons d'altres tests)
    MLXChatNode._model = None
    MLXChatNode._config = None
    MLXChatNode._is_vlm = False
    LlamaCppChatNode._pool = None
    LlamaCppChatNode._config = None
    yield
    (MLXChatNode._model, MLXChatNode._config, MLXChatNode._is_vlm,
     LlamaCppChatNode._pool, LlamaCppChatNode._config) = saved


# ── capa 1: apply_config del node (on viuen els privats) ───────────────────

def test_mlx_apply_config_resets_class_singletons():
    from plugins.mlx_module.core.chat import MLXChatNode
    cfg_a = SimpleNamespace(model_path="/models/A")
    cfg_b = SimpleNamespace(model_path="/models/B")
    node = MLXChatNode(config=cfg_a)
    MLXChatNode._model = object()      # simula model carregat
    MLXChatNode._is_vlm = True
    node.apply_config(cfg_b)
    assert node.config is cfg_b
    assert MLXChatNode._config is cfg_b
    assert MLXChatNode._model is None          # força recàrrega
    assert MLXChatNode._is_vlm is False        # re-detecció VLM (alineat amb __init__)


@patch("plugins.llama_cpp_module.core.chat.ModelPool")
def test_llama_apply_config_rebuilds_pool(MockPool):
    from plugins.llama_cpp_module.core.chat import LlamaCppChatNode
    pool_a, pool_b = Mock(name="pool_a"), Mock(name="pool_b")
    MockPool.side_effect = [pool_a, pool_b]    # instàncies distintes per crida
    cfg_a = SimpleNamespace(model_path="/models/A", max_sessions=2)
    cfg_b = SimpleNamespace(model_path="/models/B", max_sessions=2)
    node = LlamaCppChatNode(config=cfg_a)      # ModelPool(cfg_a) → pool_a
    old_pool = LlamaCppChatNode._pool
    assert old_pool is pool_a
    node.apply_config(cfg_b)                    # ModelPool(cfg_b) → pool_b
    pool_a.destroy_all.assert_called_once()     # vell pool destruït
    assert LlamaCppChatNode._config is cfg_b
    assert LlamaCppChatNode._pool is pool_b     # pool nou, no el vell
    assert MockPool.call_args_list[-1].args == (cfg_b,)  # construït amb cfg_b


# ── layer 2: the module's switch_model (decides + delegates) ─────────────────────

def test_mlx_module_switch_model_delegates():
    from plugins.mlx_module.module import MLXModule
    m = MLXModule()
    m._node = Mock()
    m._node.config.model_path = "/models/A"
    assert m.switch_model(SimpleNamespace(model_path="/models/A")) is False  # mateix path
    m._node.apply_config.assert_not_called()
    cfg_b = SimpleNamespace(model_path="/models/B")
    assert m.switch_model(cfg_b) is True
    m._node.apply_config.assert_called_once_with(cfg_b)
    m._node = None
    assert m.switch_model(cfg_b) is False       # no node → no-op segur


def test_llama_module_switch_model_delegates():
    from plugins.llama_cpp_module.module import LlamaCppModule
    m = LlamaCppModule()
    m._node = Mock()
    m._node.config.model_path = "/models/A"
    assert m.switch_model(SimpleNamespace(model_path="/models/A")) is False
    m._node.apply_config.assert_not_called()
    cfg_b = SimpleNamespace(model_path="/models/B")
    assert m.switch_model(cfg_b) is True
    m._node.apply_config.assert_called_once_with(cfg_b)
    m._node = None
    assert m.switch_model(cfg_b) is False


# ── capa 3: routes_chat delega (anti-regressió de l'encapsulament) ─────────

def test_routes_chat_mlx_delegates_to_public_switch(monkeypatch):
    from plugins.web_ui_module.api import routes_chat
    from plugins.mlx_module.core.config import MLXConfig
    monkeypatch.setattr(MLXConfig, "from_env", lambda: SimpleNamespace(model_path="/models/B"))
    engine = Mock()
    engine.switch_model.return_value = True
    routes_chat._switch_mlx_model(engine, Path("/models/B"))
    engine.switch_model.assert_called_once()
    assert engine.switch_model.call_args.args[0].model_path == "/models/B"


def test_routes_chat_llama_delegates_to_public_switch(monkeypatch):
    from plugins.web_ui_module.api import routes_chat
    from plugins.llama_cpp_module.core.config import LlamaCppConfig
    monkeypatch.setattr(LlamaCppConfig, "from_env", lambda: SimpleNamespace(model_path="/models/B"))
    engine = Mock()
    engine.switch_model.return_value = True
    routes_chat._switch_llama_cpp_model(engine, Path("/models/B"))
    engine.switch_model.assert_called_once()
    assert engine.switch_model.call_args.args[0].model_path == "/models/B"
