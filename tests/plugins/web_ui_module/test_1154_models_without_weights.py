"""#1154: a model directory without weights is not a model.

The Qwen3.5-35B-A3B-4bit had its weights moved out and kept its `config.json`.
The scan listed it (it only asked for the config), the browser selected it, and
the first message died on mlx_lm's "No safetensors found". Two halves, both
checked: the dropdown does not offer it, and a switch to it that arrives anyway
(a stale selection, an old session's model) says in words what is missing.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.endpoints.chat_engines.routing import engine_error_to_http
from core.paths.helpers import has_model_weights
from plugins.web_ui_module.api.routes_auth import _scan_mlx_backend


def _model(root, name, *, weights: bytes | None = b"x", nested=False):
    """A model directory: always a config, and weights as asked."""
    d = root / name
    d.mkdir()
    (d / "config.json").write_text("{}")
    if weights is not None:
        target = d / "sub" if nested else d
        target.mkdir(exist_ok=True)
        (target / "model.safetensors").write_bytes(weights)
    return d


class TestHasModelWeights:
    def test_a_top_level_safetensors_is_a_model(self, tmp_path):
        assert has_model_weights(_model(tmp_path, "real"))

    def test_a_config_alone_is_not(self, tmp_path):
        assert not has_model_weights(_model(tmp_path, "35b", weights=None))

    def test_an_empty_placeholder_is_not(self, tmp_path):
        assert not has_model_weights(_model(tmp_path, "cut", weights=b""))

    def test_weights_in_a_subfolder_are_not_where_mlx_lm_looks(self, tmp_path):
        assert not has_model_weights(_model(tmp_path, "nested", nested=True))

    def test_a_broken_symlink_is_not(self, tmp_path):
        d = _model(tmp_path, "moved", weights=None)
        (d / "model.safetensors").symlink_to(tmp_path / "gone.safetensors")
        assert not has_model_weights(d)

    def test_a_missing_directory_is_not(self, tmp_path):
        assert not has_model_weights(tmp_path / "nope")


class TestTheDropdownDoesNotOfferIt:
    def test_the_scan_lists_only_models_with_weights(self, tmp_path):
        _model(tmp_path, "Qwen-Real")
        _model(tmp_path, "Qwen3.5-35B-A3B-4bit", weights=None)
        _model(tmp_path, "cut", weights=b"")
        names = [m["name"] for m in _scan_mlx_backend(tmp_path)["models"]]
        assert names == ["Qwen-Real"]

    def test_no_mlx_backend_when_no_model_has_weights(self, tmp_path):
        _model(tmp_path, "Qwen3.5-35B-A3B-4bit", weights=None)
        assert _scan_mlx_backend(tmp_path) is None


class TestASwitchToItSaysWhatIsMissing:
    def _module(self):
        from plugins.mlx_module.module import MLXModule

        module = MLXModule()
        module._node = MagicMock()
        module._node.config.model_path = "/somewhere/else"
        return module

    def test_it_is_refused_before_any_state_changes(self, tmp_path):
        module = self._module()
        d = _model(tmp_path, "Qwen3.5-35B-A3B-4bit", weights=None)
        with pytest.raises(ValueError) as raised:
            module.switch_model_by_path(str(d))
        assert "Qwen3.5-35B-A3B-4bit" in str(raised.value)
        assert "weights" in str(raised.value)
        module._node.apply_config.assert_not_called()

    def test_the_cascade_policy_turns_it_into_a_404_with_that_text(self, tmp_path):
        """The switch says, in words, what is missing — the very fix of #1154 (it
        used to reach the user as nothing readable) — and the client gets those
        words whole: written for the user, not an engine's raw text (P2-7)."""
        d = _model(tmp_path, "Qwen3.5-35B-A3B-4bit", weights=None)
        with pytest.raises(ValueError) as raised:
            self._module().switch_model_by_path(str(d))
        status, detail = engine_error_to_http(raised.value, "mlx", "en")
        assert status == 404
        assert detail == str(raised.value) and "weights" in detail

    def test_a_model_with_weights_still_switches(self, tmp_path):
        module = self._module()
        assert module.switch_model_by_path(str(_model(tmp_path, "real"))) is True
        module._node.apply_config.assert_called_once()


# ── the other doors that take a model directory ─────────────────────────────


class TestTheOtherDoorsAgree:
    def test_validate_refuses_a_config_without_weights(self, tmp_path):
        from plugins.mlx_module.core.config import MLXConfig

        assert MLXConfig(model_path=str(_model(tmp_path, "35b", weights=None))).validate() is False
        assert MLXConfig(model_path=str(_model(tmp_path, "real"))).validate() is True

    def test_autodiscover_skips_a_config_without_weights(self, tmp_path, monkeypatch):
        """Alphabetically first, so before the fix the engine booted on it."""
        import core.paths.helpers as ph
        from plugins.mlx_module.core.config import MLXConfig

        _model(tmp_path, "A-no-weights", weights=None)
        _model(tmp_path, "B-real")
        monkeypatch.setattr(ph, "get_models_dir", lambda: tmp_path)
        assert MLXConfig._model_path_autodiscover().endswith("B-real")

    def test_a_dangling_symlink_beside_a_real_shard_does_not_hide_it(self, tmp_path):
        d = _model(tmp_path, "sharded", weights=None)
        (d / "model-00001-of-00002.safetensors").symlink_to(tmp_path / "gone.safetensors")
        (d / "model-00002-of-00002.safetensors").write_bytes(b"x")
        assert has_model_weights(d)


class TestSetBackendDoesNotPersistIt:
    """`POST /ui/backend` wrote the model to .env after a config-only check."""

    @pytest.fixture
    def post_backend(self, tmp_path, monkeypatch):
        import asyncio

        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        import core.paths.helpers as ph
        from core import runtime_state
        from core.dependencies import limiter
        from plugins.web_ui_module.api import routes_auth
        from plugins.web_ui_module.manifest import router_public
        from plugins.web_ui_module.module import WebUIModule

        monkeypatch.setenv("NEXE_API_BASE_URL", "http://127.0.0.1:9119")
        monkeypatch.setenv("NEXE_PRIMARY_API_KEY", "k1154")
        monkeypatch.delenv("NEXE_ADMIN_API_KEY", raising=False)
        monkeypatch.setattr(limiter, "enabled", False)
        monkeypatch.setattr(ph, "get_models_dir", lambda: tmp_path)
        # What the route would write to .env, and the overrides it would leave behind.
        persisted: list = []
        monkeypatch.setattr(routes_auth, "_persist_env_vars", persisted.append)
        monkeypatch.setattr(runtime_state, "set_override", lambda *_a, **_k: None)
        mod = WebUIModule()
        asyncio.run(mod.initialize({}))
        app = FastAPI()
        app.include_router(mod.get_router())
        app.include_router(router_public)
        client = TestClient(app, raise_server_exceptions=False)

        def post(model):
            r = client.post("/ui/backend", headers={"X-API-Key": "k1154"}, json={"backend": "mlx", "model": model})
            return r, persisted

        return post

    def test_a_config_without_weights_is_a_400_and_not_persisted(self, tmp_path, post_backend):
        _model(tmp_path, "Qwen3.5-35B-A3B-4bit", weights=None)
        r, persisted = post_backend("Qwen3.5-35B-A3B-4bit")
        assert r.status_code == 400
        assert "not found" in r.json()["detail"]
        assert persisted == []

    def test_a_model_with_weights_is_accepted(self, tmp_path, post_backend):
        _model(tmp_path, "Qwen-Real")
        r, persisted = post_backend("Qwen-Real")
        assert r.status_code == 200
        assert persisted == [{"NEXE_MODEL_ENGINE": "mlx", "NEXE_DEFAULT_MODEL": "Qwen-Real"}]
