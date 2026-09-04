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

F-D block 5 moved the first layer twice over: the path resolution went to the
core (switch_engine_model, which any door could call) and the validation went
into the engine module itself (switch_model_by_path), because what a model of a
given kind looks like is that engine's knowledge and the core may not import a
plugin to ask. The guarantee is unchanged and is still checked at both halves.
"""

import json
from unittest.mock import MagicMock

import pytest

from core.endpoints.chat_engines.model_switch import (
    resolve_local_model_path,
    switch_engine_model,
)
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


def _mlx_module():
    """A real MLXModule with a live node — the validation runs for real, and
    apply_config is what must NOT be reached."""
    from plugins.mlx_module.module import MLXModule

    module = MLXModule()
    node = MagicMock()
    node.config.model_path = "/somewhere/else"
    module._node = node
    return module, node


def _llama_module():
    from plugins.llama_cpp_module.module import LlamaCppModule

    module = LlamaCppModule()
    node = MagicMock()
    node.config.model_path = "/somewhere/else"
    module._node = node
    return module, node


class TestTheEngineValidatesBeforeItSwitches:
    """Layer 1a — the plugin half. Driven on the real module, not a mock of it."""

    async def test_ghost_dir_raises_not_found(self, models_dir):
        """The exact 8 GB M1 repro: dir EXISTS but has no config.json."""
        module, node = _mlx_module()
        with pytest.raises(ValueError, match="not found"):
            await switch_engine_model(module, "mlx", "mlx")
        node.apply_config.assert_not_called()

    async def test_missing_path_raises_not_found(self, models_dir):
        """The old silent-skip: user kept chatting with the OLD model."""
        module, node = _mlx_module()
        with pytest.raises(ValueError, match="not found"):
            await switch_engine_model(module, "mlx", "no-such")
        node.apply_config.assert_not_called()

    async def test_llamacpp_requires_a_gguf_file(self, models_dir):
        module, node = _llama_module()
        with pytest.raises(ValueError, match="not found"):
            await switch_engine_model(module, "llama_cpp", "empty-dir")
        node.apply_config.assert_not_called()

    async def test_a_real_gguf_gets_through(self, models_dir, monkeypatch):
        """The positive half. Without it the validation could be inverted —
        raising on the valid file and letting the ghost through — and every
        other test here would stay green. It was in the version before F-D
        block 5 and I dropped it moving the checks into the plugin."""
        from types import SimpleNamespace

        from plugins.llama_cpp_module.core.config import LlamaCppConfig

        module, _node = _llama_module()
        monkeypatch.setattr(
            LlamaCppConfig, "from_env",
            lambda: SimpleNamespace(model_path=str(models_dir / "some.gguf")),
        )
        await switch_engine_model(module, "llama_cpp", "some.gguf")

    async def test_a_real_mlx_model_gets_through(self, models_dir, monkeypatch):
        from types import SimpleNamespace

        from plugins.mlx_module.core.config import MLXConfig

        module, _node = _mlx_module()
        monkeypatch.setattr(
            MLXConfig, "from_env",
            lambda: SimpleNamespace(model_path=str(models_dir / "Qwen-Real")),
        )
        await switch_engine_model(module, "mlx", "Qwen-Real")


class TestTheCoreResolvesAndAsks:
    """Layer 1b — the core half: find the file under the models dir, ask the
    engine. It knows nothing about what makes a model valid."""

    async def test_a_real_model_reaches_the_engine(self, models_dir):
        engine = MagicMock()
        engine.switch_model_by_path.return_value = True
        assert await switch_engine_model(engine, "mlx", "Qwen-Real") is True
        assert engine.switch_model_by_path.call_args.args[0].name == "Qwen-Real"

    def test_the_path_is_resolved_under_the_models_dir(self, models_dir):
        assert resolve_local_model_path("Qwen-Real").parent == models_dir

    async def test_an_engine_without_the_contract_keeps_its_model(self, models_dir):
        """Ollama picks its model per request, and so would any engine written
        before this contract. Not being able to switch is not a failed turn."""
        engine = MagicMock(spec=["chat"])
        assert await switch_engine_model(engine, "ollama", "whatever") is False


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
