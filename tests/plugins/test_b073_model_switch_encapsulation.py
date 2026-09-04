"""B073 — el canvi de model des del web_ui ha de passar per una API pública.

Abans del fix, routes_chat._switch_{mlx,llama_cpp}_model feien cirurgia a mà
sobre atributs privats de classe d'altres plugins (MLXChatNode._model,
LlamaCppChatNode._pool/_config). Sense cap test, un refactor d'aquells motors
trencaria el canvi de model en silenci.

Aquests tests fixen el contracte públic:
  node.apply_config(new_config)  -> reset dels singletons de classe (al plugin)
  module.switch_model(new_config) -> decideix i delega a apply_config
  module.switch_model_by_path(path) -> construeix la config i crida switch_model
i NO toca cap atribut privat de classe. (F-D bloc 5: l'últim pas vivia a
routes_chat._switch_{mlx,llama_cpp}_model i ha baixat dins de cada mòdul.)
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


# ── capa 3: switch_model_by_path delega (anti-regressió de l'encapsulament) ─
#
# F-D block 5: aquestes dues comprovacions vivien sobre `routes_chat._switch_
# mlx_model` / `_switch_llama_cpp_model`. Les funcions han baixat dins del mòdul
# de cada motor (`switch_model_by_path`) perquè el nucli no pot importar un
# plugin per construir-li la config. La garantia és la mateixa i és on toca: qui
# canvia de model passa pel `switch_model` públic i no toca mai els privats del
# node.

def test_mlx_switch_by_path_delegates_to_public_switch(monkeypatch, tmp_path):
    from plugins.mlx_module.core.config import MLXConfig
    from plugins.mlx_module.module import MLXModule

    model = tmp_path / "B"
    model.mkdir()
    (model / "config.json").write_text("{}")
    monkeypatch.setattr(MLXConfig, "from_env", lambda: SimpleNamespace(model_path=str(model)))

    module = MLXModule()
    module.switch_model = Mock(return_value=True)
    assert module.switch_model_by_path(model) is True
    module.switch_model.assert_called_once()
    assert module.switch_model.call_args.args[0].model_path == str(model)


def test_llama_switch_by_path_delegates_to_public_switch(monkeypatch, tmp_path):
    from plugins.llama_cpp_module.core.config import LlamaCppConfig
    from plugins.llama_cpp_module.module import LlamaCppModule

    model = tmp_path / "B.gguf"
    model.write_bytes(b"g")
    monkeypatch.setattr(LlamaCppConfig, "from_env", lambda: SimpleNamespace(model_path=str(model)))

    module = LlamaCppModule()
    module.switch_model = Mock(return_value=True)
    assert module.switch_model_by_path(model) is True
    module.switch_model.assert_called_once()
    assert module.switch_model.call_args.args[0].model_path == str(model)


def test_the_env_override_never_leaks_past_the_switch(monkeypatch, tmp_path):
    """P0-3: the override that lets from_env() see the new path is restored
    whether the switch works or blows up, or the next request that names no
    model inherits this one's."""
    from core.runtime_state import get_override
    from plugins.mlx_module.core.config import MLXConfig
    from plugins.mlx_module.module import MLXModule

    model = tmp_path / "B"
    model.mkdir()
    (model / "config.json").write_text("{}")

    def _boom():
        raise RuntimeError("from_env exploded")

    monkeypatch.setattr(MLXConfig, "from_env", _boom)
    module = MLXModule()
    module.switch_model = Mock(return_value=True)
    with pytest.raises(RuntimeError):
        module.switch_model_by_path(model)
    assert get_override("NEXE_MLX_MODEL") is None
