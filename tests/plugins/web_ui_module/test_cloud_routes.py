"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/plugins/web_ui_module/test_cloud_routes.py
Description: API providers, phase 2 — the selector's side: the "API" group of
    `GET /ui/backends`, picking it with `POST /ui/backend` and the switch
    `POST /ui/cloud-engines`. Through the real registered routes; no network,
    a key that is obviously fake, and `.env` never written (the persist
    helper is replaced and its calls recorded).

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from core import runtime_state
from core.providers.cloud import ALLOW_CLOUD_ENV
from plugins.web_ui_module.api import routes_auth

FAKE_KEY = "FAKE-KEY-for-tests-7f3a9c1e-not-a-secret"
ROUTES = "plugins.web_ui_module.api.routes_auth"


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    runtime_state.reset()
    for var in (ALLOW_CLOUD_ENV, "DEEPSEEK_API_KEY", "OPENAI_API_KEY", "NEXE_MODEL_ENGINE", "NEXE_DEFAULT_MODEL"):
        monkeypatch.delenv(var, raising=False)
    yield
    runtime_state.reset()


@pytest.fixture
def persisted():
    with patch(f"{ROUTES}._persist_env_vars") as persist:
        yield persist


@pytest.fixture
def client(persisted):
    async def _auth():
        return None

    router = APIRouter(prefix="/ui")
    routes_auth.register_auth_routes(router, require_ui_auth=_auth, session_mgr=MagicMock())
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _module_manager(*loaded):
    def get_module(name):
        return SimpleNamespace(instance=object()) if name in loaded else None
    return SimpleNamespace(registry=SimpleNamespace(get_module=get_module))


def _backends(client, tmp_path, *, loaded=("api_module",), ollama=None):
    state = SimpleNamespace(module_manager=_module_manager(*loaded))
    with patch("core.lifespan.get_server_state", return_value=state), \
         patch(f"{ROUTES}._resolve_models_dir", return_value=tmp_path / "no-models"), \
         patch(f"{ROUTES}._scan_ollama_backend", new=AsyncMock(return_value=ollama)):
        return client.get("/ui/backends")


def _open(monkeypatch, **keys):
    monkeypatch.setenv(ALLOW_CLOUD_ENV, "1")
    monkeypatch.setenv("DEEPSEEK_API_KEY", FAKE_KEY)
    for name, value in keys.items():
        monkeypatch.setenv(name, value)


LOCAL = {"id": "ollama", "name": "Ollama", "models": [{"name": "llama3.2:3b", "size_gb": 2}], "active": False, "connected": True}


# ------------------------------------------------------------------ the group

def test_with_the_switch_off_there_is_no_api_group_and_the_switch_reads_off(client, tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", FAKE_KEY)
    body = _backends(client, tmp_path, ollama=dict(LOCAL)).json()
    assert [b["id"] for b in body["backends"]] == ["ollama"]
    assert body["cloud"]["allowed"] is False
    assert {p["key"]: p["configured"] for p in body["cloud"]["providers"]} == {"deepseek": True, "openai": False, "anthropic": False}


def test_with_the_switch_on_a_configured_provider_adds_the_group_last_with_per_model_vision(client, tmp_path, monkeypatch):
    _open(monkeypatch, OPENAI_API_KEY=FAKE_KEY)
    body = _backends(client, tmp_path, ollama=dict(LOCAL)).json()
    assert [b["id"] for b in body["backends"]] == ["ollama", "api"]
    group = body["backends"][-1]
    assert group["name"] == "API" and group["cloud"] is True and group["connected"] is True and group["active"] is False
    models = {m["name"]: m for m in group["models"]}
    assert set(models) == {"deepseek-chat", "deepseek-reasoner", "gpt-4o", "gpt-4o-mini"}
    assert models["deepseek-chat"]["provider_name"] == "DeepSeek" and models["deepseek-chat"]["vision"] is False
    assert models["gpt-4o"]["provider"] == "openai" and models["gpt-4o"]["vision"] is True
    assert body["cloud"]["allowed"] is True


def test_only_providers_with_a_key_contribute_models(client, tmp_path, monkeypatch):
    _open(monkeypatch)
    group = _backends(client, tmp_path).json()["backends"][-1]
    assert {m["provider"] for m in group["models"]} == {"deepseek"}


def test_no_configured_provider_no_group(client, tmp_path, monkeypatch):
    monkeypatch.setenv(ALLOW_CLOUD_ENV, "1")
    assert _backends(client, tmp_path, ollama=dict(LOCAL)).json()["backends"][0]["id"] == "ollama"
    assert "api" not in [b["id"] for b in _backends(client, tmp_path).json()["backends"]]


def test_an_unloaded_engine_module_means_no_group_nothing_could_serve_it(client, tmp_path, monkeypatch):
    _open(monkeypatch)
    assert "api" not in [b["id"] for b in _backends(client, tmp_path, loaded=()).json()["backends"]]


def test_a_dead_local_engine_never_makes_the_api_the_active_or_the_default(client, tmp_path, monkeypatch):
    """`_mark_active_backend` falls back to the first connected backend with
    models and PERSISTS it; the cloud must not be a candidate for that."""
    _open(monkeypatch, NEXE_MODEL_ENGINE="ollama")
    dead = dict(LOCAL, connected=False)
    body = _backends(client, tmp_path, ollama=dead).json()
    api = [b for b in body["backends"] if b["id"] == "api"][0]
    assert api["active"] is False
    assert body["current_backend"] != "api"
    assert runtime_state.get_override("NEXE_MODEL_ENGINE") is None


def test_the_listing_never_carries_a_key(client, tmp_path, monkeypatch):
    _open(monkeypatch, OPENAI_API_KEY=FAKE_KEY)
    assert FAKE_KEY not in _backends(client, tmp_path, ollama=dict(LOCAL)).text


# ------------------------------------------------------------ picking the API

def test_picking_an_api_model_with_the_switch_off_is_a_403_with_a_code(client, persisted, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", FAKE_KEY)
    resp = client.post("/ui/backend", json={"backend": "api", "model": "deepseek-chat"})
    assert resp.status_code == 403 and resp.json()["detail"]["code"] == "cloud_engines_disabled"
    persisted.assert_not_called()


@pytest.mark.parametrize("model,code", [("llama3.2:3b", "cloud_model_not_allowed"), ("", "cloud_model_not_allowed")])
def test_picking_a_model_no_provider_owns_is_a_400(client, persisted, monkeypatch, model, code):
    _open(monkeypatch)
    resp = client.post("/ui/backend", json={"backend": "api", "model": model})
    assert resp.status_code == 400 and resp.json()["detail"]["code"] == code
    persisted.assert_not_called()


def test_picking_a_provider_without_its_key_is_a_400(client, persisted, monkeypatch):
    monkeypatch.setenv(ALLOW_CLOUD_ENV, "1")
    resp = client.post("/ui/backend", json={"backend": "api", "model": "deepseek-chat"})
    assert resp.status_code == 400 and resp.json()["detail"]["code"] == "cloud_provider_not_configured"


@pytest.mark.parametrize("spelling", ["api", "API", " Api "])
def test_the_choice_is_the_browsers_nothing_is_persisted_and_no_default_changes(client, persisted, monkeypatch, spelling):
    """A persisted "api" would make the cloud the engine of every request that
    names none, and the cloud model the default of the local engines."""
    _open(monkeypatch)
    resp = client.post("/ui/backend", json={"backend": spelling, "model": "deepseek-chat"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["backend"] == "api" and body["model"] == "deepseek-chat" and body["persisted"] is False
    assert body["provider"] == "deepseek" and body["ollama_started"] is False
    persisted.assert_not_called()
    assert runtime_state.get_override("NEXE_MODEL_ENGINE") is None
    assert runtime_state.get_override("NEXE_DEFAULT_MODEL") is None
    assert FAKE_KEY not in resp.text


def test_a_local_choice_still_persists_as_before(client, persisted, monkeypatch):
    monkeypatch.setenv("NEXE_MODEL_ENGINE", "auto")
    resp = client.post("/ui/backend", json={"backend": "auto", "model": ""})
    assert resp.status_code == 200
    persisted.assert_called_once_with({"NEXE_MODEL_ENGINE": "auto"})


def test_an_unknown_backend_name_is_still_refused_and_lists_the_api(client):
    resp = client.post("/ui/backend", json={"backend": "banana"})
    assert resp.status_code == 400 and "api" in resp.json()["detail"]


# ------------------------------------------------------------------ the switch

def test_the_switch_can_be_turned_on_and_off_and_is_persisted_like_the_other_parameters(client, persisted):
    resp = client.post("/ui/cloud-engines", json={"enabled": True})
    assert resp.status_code == 200 and resp.json() == {"status": "ok", "allowed": True}
    persisted.assert_called_with({ALLOW_CLOUD_ENV: "1"})
    resp = client.post("/ui/cloud-engines", json={"enabled": False})
    assert resp.json()["allowed"] is False
    persisted.assert_called_with({ALLOW_CLOUD_ENV: "0"})
    from core.providers.cloud import cloud_engines_allowed
    assert cloud_engines_allowed() is False


@pytest.mark.parametrize("value", ["false", "true", 1, 0, None, [], "yes"])
def test_the_switch_takes_a_real_boolean_only_a_string_is_never_read_as_truthy(client, persisted, value):
    resp = client.post("/ui/cloud-engines", json={"enabled": value})
    assert resp.status_code == 400
    persisted.assert_not_called()
    from core.providers.cloud import cloud_engines_allowed
    assert cloud_engines_allowed() is False


def test_the_switch_requires_the_field(client, persisted):
    assert client.post("/ui/cloud-engines", json={}).status_code == 400
    persisted.assert_not_called()


def test_the_routes_sit_behind_the_ui_auth_dependency():
    from fastapi import HTTPException

    async def deny():
        raise HTTPException(status_code=401, detail="no")

    router = APIRouter(prefix="/ui")
    routes_auth.register_auth_routes(router, require_ui_auth=deny, session_mgr=MagicMock())
    app = FastAPI()
    app.include_router(router)
    http = TestClient(app)
    assert http.post("/ui/cloud-engines", json={"enabled": True}).status_code == 401
    assert http.post("/ui/backend", json={"backend": "api", "model": "deepseek-chat"}).status_code == 401
    assert http.get("/ui/backends").status_code == 401
    assert runtime_state.get_override(ALLOW_CLOUD_ENV) is None


def test_the_dropdown_id_of_the_api_engine_is_itself():
    """`_BACKEND_IDS` maps an engine name to its dropdown id; the API's is "api",
    and it is not in the cascade that table is read through."""
    from core.endpoints.chat_engines.routing import ENGINE_CASCADE
    assert routes_auth._backend_ids()["api"] == "api"
    assert "api" not in routes_auth._auto_backend_cascade() and "api" not in ENGINE_CASCADE
