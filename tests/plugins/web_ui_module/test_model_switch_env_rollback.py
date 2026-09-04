"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: plugins/web_ui_module/tests/test_model_switch_env_rollback.py
Description: Regression guard P0-3 env rollback — `NEXE_MLX_MODEL` and
             `NEXE_LLAMA_CPP_MODEL` must be restored to their previous state
             after the UI model selector mutates them to build a `from_env()`.
             Without rollback, subsequent requests without `body.model`
             would inherit the mutated value.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import os
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


class TestTheOverrideCarriesThePath:
    """F5.6 BUG-NC-18 part 2 — the model path travels through the runtime_state
    singleton, never through os.environ: env writes are thread-unsafe and the
    singleton stays consistent across concurrent requests.

    This used to be a source guard that grepped routes_chat.py for the substring
    `set_override("NEXE_MLX_MODEL"`. F-D block 5 moved that code into the engine
    modules, which would have turned the guard red for a move — and a substring
    in a file was never the guarantee anyway. It is asserted here at the moment
    that matters: what from_env() can see while it builds the config.
    """

    def _observe(self, monkeypatch, config_cls, key, model_path):
        seen = {}

        def _capture():
            from core.runtime_state import get_override

            seen["override"] = get_override(key)
            seen["env"] = os.environ.get(key)
            return SimpleNamespace(model_path=str(model_path))

        monkeypatch.setattr(config_cls, "from_env", _capture)
        return seen

    def test_mlx_reads_the_path_from_the_override_not_the_env(self, tmp_path, monkeypatch):
        from core.runtime_state import get_override
        from plugins.mlx_module.core.config import MLXConfig
        from plugins.mlx_module.module import MLXModule

        model = tmp_path / "B"
        model.mkdir()
        (model / "config.json").write_text("{}")
        monkeypatch.delenv("NEXE_MLX_MODEL", raising=False)
        seen = self._observe(monkeypatch, MLXConfig, "NEXE_MLX_MODEL", model)

        module = MLXModule()
        module.switch_model = MagicMock(return_value=True)
        module.switch_model_by_path(model)

        assert seen["override"] == str(model), "from_env() could not see the new path"
        assert seen["env"] is None, "the path was written into os.environ"
        assert get_override("NEXE_MLX_MODEL") is None, "the override outlived the switch"

    def test_llama_cpp_reads_the_path_from_the_override_not_the_env(self, tmp_path, monkeypatch):
        from core.runtime_state import get_override
        from plugins.llama_cpp_module.core.config import LlamaCppConfig
        from plugins.llama_cpp_module.module import LlamaCppModule

        model = tmp_path / "B.gguf"
        model.write_bytes(b"g")
        monkeypatch.delenv("NEXE_LLAMA_CPP_MODEL", raising=False)
        seen = self._observe(monkeypatch, LlamaCppConfig, "NEXE_LLAMA_CPP_MODEL", model)

        module = LlamaCppModule()
        module.switch_model = MagicMock(return_value=True)
        module.switch_model_by_path(model)

        assert seen["override"] == str(model), "from_env() could not see the new path"
        assert seen["env"] is None, "the path was written into os.environ"
        assert get_override("NEXE_LLAMA_CPP_MODEL") is None, "the override outlived the switch"
