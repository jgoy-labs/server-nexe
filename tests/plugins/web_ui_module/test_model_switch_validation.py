"""FD-S4 — a model switch must validate BEFORE mutating any state.

Field incident (8 GB M1, 2026-07-23): the models dir contained a grouping
folder ``mlx/`` (no config.json). The scan listed it as a model, the UI sent
``model="mlx"``, the bare ``.exists()`` gate let it through, the module
switched its global config to the ghost path, the RAM guard estimated a model
that did not exist, and the user got a raw FileNotFoundError. Worse: when the
gate DID catch a missing path, it skipped silently — the user kept chatting
with the OLD model with no signal.

Three layers, all backend: routes (clean 404), module (state never mutates),
scan (ghosts never reach the dropdown).
"""

import json
from unittest.mock import MagicMock

import pytest

from plugins.web_ui_module.api.routes_chat import _switch_engine_model
from plugins.web_ui_module.api.routes_auth import _scan_mlx_backend


@pytest.fixture()
def models_dir(tmp_path, monkeypatch):
    """A models dir with one REAL model and one ghost grouping folder."""
    real = tmp_path / "Qwen-Real"
    real.mkdir()
    (real / "config.json").write_text(json.dumps({
        "model_type": "test", "num_hidden_layers": 2,
        "num_key_value_heads": 2, "head_dim": 64,
    }))
    (real / "model.safetensors").write_bytes(b"x")
    (tmp_path / "mlx").mkdir()          # the 8 GB M1 ghost, literally
    (tmp_path / "empty-dir").mkdir()
    gguf = tmp_path / "some.gguf"
    gguf.write_bytes(b"g")
    import core.paths.helpers as ph
    monkeypatch.setattr(ph, "get_models_dir", lambda: tmp_path)
    # routes_chat imports get_models_dir inside the function → patch source.
    return tmp_path


class TestSwitchEngineModel:
    async def test_ghost_dir_raises_not_found(self, models_dir):
        """The exact 8 GB M1 repro: dir EXISTS but has no config.json."""
        engine = MagicMock()
        with pytest.raises(ValueError, match="not found"):
            await _switch_engine_model(engine, "mlx_module", {}, "mlx")
        engine.switch_model.assert_not_called()

    async def test_missing_path_raises_not_found(self, models_dir):
        """The old silent-skip: user kept chatting with the OLD model."""
        engine = MagicMock()
        with pytest.raises(ValueError, match="not found"):
            await _switch_engine_model(engine, "mlx_module", {}, "no-such")

    async def test_real_model_switches(self, models_dir, monkeypatch):
        import plugins.web_ui_module.api.routes_chat as rc
        called = {}
        monkeypatch.setattr(
            rc, "_switch_mlx_model", lambda e, p: called.setdefault("path", p)
        )
        await _switch_engine_model(MagicMock(), "mlx_module", {}, "Qwen-Real")
        assert called["path"].name == "Qwen-Real"

    async def test_llamacpp_requires_a_gguf_file(self, models_dir, monkeypatch):
        import plugins.web_ui_module.api.routes_chat as rc
        monkeypatch.setattr(rc, "_switch_llama_cpp_model", lambda e, p: None)
        with pytest.raises(ValueError, match="not found"):
            await _switch_engine_model(MagicMock(), "llama_cpp_module", {}, "empty-dir")
        # a real .gguf passes
        await _switch_engine_model(MagicMock(), "llama_cpp_module", {}, "some.gguf")


class TestModuleBelt:
    """The module's state must NEVER mutate to an invalid config."""

    def test_mlx_switch_refuses_invalid_config(self, tmp_path):
        """Mutation control: removing the validate() call in
        MLXModule.switch_model makes apply_config run and this fail."""
        from plugins.mlx_module.core.config import MLXConfig
        from plugins.mlx_module.module import MLXModule

        ghost = tmp_path / "ghost"
        ghost.mkdir()  # exists, but no config.json → validate() False
        module = MLXModule()
        node = MagicMock()
        node.config.model_path = "/somewhere/else"
        module._node = node
        assert module.switch_model(MLXConfig(model_path=str(ghost))) is False
        node.apply_config.assert_not_called()

    def test_mlx_switch_accepts_valid_config(self, tmp_path):
        from plugins.mlx_module.core.config import MLXConfig
        from plugins.mlx_module.module import MLXModule

        real = tmp_path / "real"
        real.mkdir()
        (real / "config.json").write_text("{}")
        module = MLXModule()
        node = MagicMock()
        node.config.model_path = "/somewhere/else"
        module._node = node
        assert module.switch_model(MLXConfig(model_path=str(real))) is True
        node.apply_config.assert_called_once()


class TestScanFiltersGhosts:
    def test_scan_lists_only_real_models(self, models_dir):
        """RED before FD-S4: the bare iterdir listed 'mlx' and 'empty-dir'."""
        result = _scan_mlx_backend(models_dir)
        names = [m["name"] for m in result["models"]]
        assert names == ["Qwen-Real"]

    def test_scan_returns_none_when_only_ghosts(self, tmp_path):
        (tmp_path / "mlx").mkdir()
        assert _scan_mlx_backend(tmp_path) is None


class TestCuratedImportError:
    def test_mlx_import_attributeerror_is_curated(self, tmp_path, monkeypatch):
        """Finding 820's raw trace must never reach a caller again.

        Mutation control: removing the import wrap re-raises the raw
        AttributeError instead of the curated RuntimeError."""
        import builtins
        import sys
        from plugins.mlx_module.core.chat import MLXChatNode

        model_dir = tmp_path / "m"
        model_dir.mkdir()
        (model_dir / "config.json").write_text(json.dumps({"model_type": "qwen3"}))
        (model_dir / "model.safetensors").write_bytes(b"x")

        config = MagicMock()
        config.model_path = str(model_dir)
        config.max_kv_size = 4096

        real_import = builtins.__import__

        def _sabotage(name, *a, **k):
            if name == "mlx_lm":
                raise AttributeError("'str' object has no attribute '__module__'")
            return real_import(name, *a, **k)

        monkeypatch.setenv("NEXE_MLX_RAM_GUARD", "off")
        monkeypatch.delitem(sys.modules, "mlx_lm", raising=False)
        monkeypatch.setattr(builtins, "__import__", _sabotage)
        MLXChatNode._model = None
        node = MLXChatNode(config=config)
        try:
            with pytest.raises(RuntimeError, match="finding 820"):
                node._get_model()
        finally:
            MLXChatNode._model = None
