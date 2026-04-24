"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/test_removed_direct_routes_guard.py
Description: Follow-up F4.2 — RemovedDirectRoutesGuard middleware tests.
             Verifica que les rutes declarades a removed_direct_routes retornen
             403, que les rutes actives d'Ollama NO s'veuen afectades (regressió
             crítica), i que el loader rebutja plugins amb col·lisió.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from pathlib import Path

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]


# ──────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _clear_guard_registry():
    """Neteja el registry de la guarda entre tests per evitar contaminació."""
    from core import middleware as mw
    mw._REMOVED_ROUTE_REGISTRY.clear()
    mw._REMOVED_ROUTE_PATTERNS.clear()
    yield
    mw._REMOVED_ROUTE_REGISTRY.clear()
    mw._REMOVED_ROUTE_PATTERNS.clear()


def _build_guarded_app(*blocked_routes: tuple) -> FastAPI:
    """Crea una app minimal amb RemovedDirectRoutesGuard i les rutes registrades.

    Args:
        blocked_routes: Tuples (plugin_name, manifest_route, prefix) a bloquejar.
    """
    from core.middleware import register_removed_route, RemovedDirectRoutesGuard

    app = FastAPI()
    app.add_middleware(RemovedDirectRoutesGuard)

    for plugin_name, manifest_route, prefix in blocked_routes:
        register_removed_route(plugin_name, manifest_route, prefix)

    return app


# ──────────────────────────────────────────────────────────────────────────
# Tests 1-3: 403 per les 3 rutes fantasma
# ──────────────────────────────────────────────────────────────────────────

class TestBlockedRoutes:
    """Les 3 rutes declarades a removed_direct_routes han de retornar 403."""

    def test_mlx_chat_direct_returns_403(self):
        """POST /mlx/chat → 403 amb error code direct_plugin_endpoint_disabled."""
        app = _build_guarded_app(("mlx_module", "/chat", "/mlx"))
        with TestClient(app, raise_server_exceptions=False) as client:
            r = client.post("/mlx/chat", json={"messages": []})
        assert r.status_code == 403
        body = r.json()
        assert body["error"] == "direct_plugin_endpoint_disabled"
        assert body["removed_route"] == "/mlx/chat"

    def test_llama_cpp_chat_direct_returns_403(self):
        """POST /llama-cpp/chat → 403."""
        app = _build_guarded_app(("llama_cpp_module", "/chat", "/llama-cpp"))
        with TestClient(app, raise_server_exceptions=False) as client:
            r = client.post("/llama-cpp/chat", json={})
        assert r.status_code == 403
        body = r.json()
        assert body["error"] == "direct_plugin_endpoint_disabled"
        assert body["removed_route"] == "/llama-cpp/chat"

    def test_ollama_api_chat_direct_returns_403(self):
        """POST /ollama/api/chat → 403."""
        app = _build_guarded_app(("ollama_module", "/api/chat", "/ollama"))
        with TestClient(app, raise_server_exceptions=False) as client:
            r = client.post("/ollama/api/chat", json={})
        assert r.status_code == 403
        body = r.json()
        assert body["error"] == "direct_plugin_endpoint_disabled"
        assert body["removed_route"] == "/ollama/api/chat"


# ──────────────────────────────────────────────────────────────────────────
# Tests 4-5: REGRESSIÓ CRÍTICA — rutes actives d'Ollama NO afectades
# ──────────────────────────────────────────────────────────────────────────

class TestOllamaRegressions:
    """Les rutes actives d'Ollama /api/pull i DELETE /api/models/{name}
    NO han de ser afectades per la guarda."""

    def _build_ollama_app(self) -> FastAPI:
        from core.middleware import register_removed_route, RemovedDirectRoutesGuard
        from fastapi.responses import JSONResponse

        app = FastAPI()
        app.add_middleware(RemovedDirectRoutesGuard)
        register_removed_route("ollama_module", "/api/chat", "/ollama")

        # Rutes actives simulades (sense dependència real d'Ollama)
        @app.post("/ollama/api/pull")
        async def pull_model():
            return JSONResponse({"status": "ok", "action": "pull"})

        @app.delete("/ollama/api/models/{model_name}")
        async def delete_model(model_name: str):
            return JSONResponse({"status": "ok", "model": model_name})

        return app

    def test_ollama_api_pull_still_works(self):
        """REGRESSIÓ CRÍTICA: POST /ollama/api/pull NO retorna 403."""
        app = self._build_ollama_app()
        with TestClient(app, raise_server_exceptions=False) as client:
            r = client.post("/ollama/api/pull", json={"name": "llama3"})
        assert r.status_code != 403 or r.json().get("error") != "direct_plugin_endpoint_disabled", (
            "REGRESSIÓ: /ollama/api/pull bloquejat per la guarda — la implementació és incorrecta"
        )
        assert r.status_code == 200

    def test_ollama_api_models_delete_still_works(self):
        """REGRESSIÓ CRÍTICA: DELETE /ollama/api/models/foo NO retorna 403."""
        app = self._build_ollama_app()
        with TestClient(app, raise_server_exceptions=False) as client:
            r = client.delete("/ollama/api/models/llama3")
        assert r.status_code != 403 or r.json().get("error") != "direct_plugin_endpoint_disabled", (
            "REGRESSIÓ: DELETE /ollama/api/models/foo bloquejat per la guarda"
        )
        assert r.status_code == 200


# ──────────────────────────────────────────────────────────────────────────
# Test 6: Pipeline canonical NO afectat
# ──────────────────────────────────────────────────────────────────────────

class TestPipelineNotAffected:
    """Els endpoints del pipeline canònic no han de ser bloquejats."""

    def test_pipeline_endpoints_still_work(self):
        """POST /ui/chat i /v1/chat/completions NO retornen 403 per la guarda."""
        from core.middleware import register_removed_route, RemovedDirectRoutesGuard
        from fastapi.responses import JSONResponse

        app = FastAPI()
        app.add_middleware(RemovedDirectRoutesGuard)
        register_removed_route("mlx_module", "/chat", "/mlx")
        register_removed_route("ollama_module", "/api/chat", "/ollama")

        @app.post("/ui/chat")
        async def ui_chat():
            return JSONResponse({"status": "ok"})

        @app.post("/v1/chat/completions")
        async def v1_chat():
            return JSONResponse({"status": "ok"})

        with TestClient(app, raise_server_exceptions=False) as client:
            r_ui = client.post("/ui/chat", json={})
            r_v1 = client.post("/v1/chat/completions", json={})

        assert r_ui.status_code == 200, f"Pipeline /ui/chat afectat per la guarda: {r_ui.status_code}"
        assert r_v1.status_code == 200, f"Pipeline /v1/chat/completions afectat: {r_v1.status_code}"


# ──────────────────────────────────────────────────────────────────────────
# Test 7: Loader fail-fast — col·lisió removed_direct_routes ↔ router registrat
# ──────────────────────────────────────────────────────────────────────────

class TestLoaderFailFast:
    """El loader ha de rebutjar un plugin que declara removed_direct_routes
    i alhora registra la mateixa ruta."""

    def test_plugin_with_colliding_route_is_rejected(self):
        """Plugin fake declara removed=["/foo"] i registra @router.post("/foo")
        → PluginLoadError amb plugin_name i colliding_route."""
        from core.loader.protocol import PluginLoadError
        from personality.module_manager.module_manager import ModuleManager

        # Construïm un manifest_module fals
        router = APIRouter(prefix="/fake")

        @router.post("/foo")
        async def fake_endpoint():
            pass

        class FakeManifest:
            removed_direct_routes = ["/foo"]
            def get_router(self):
                return router

        mm = ModuleManager.__new__(ModuleManager)

        with pytest.raises(PluginLoadError) as exc_info:
            mm._check_removed_routes_collision(router, ["/foo"], "fake_plugin")

        err = exc_info.value
        assert err.plugin_name == "fake_plugin"
        assert err.colliding_route == "/foo"
        assert "fake_plugin" in str(err)
        assert "/foo" in str(err)


# ──────────────────────────────────────────────────────────────────────────
# Test 8: Log estructurat en accés bloquejat
# ──────────────────────────────────────────────────────────────────────────

class TestLogging:
    """La guarda ha d'emetre un log estructurat en bloquejar una petició."""

    def test_log_entry_on_blocked_access(self, caplog):
        """Una crida bloquejada emet security.plugin.direct_access_blocked
        amb els 5 camps estructurats."""
        import logging
        from core.middleware import register_removed_route, RemovedDirectRoutesGuard

        app = FastAPI()
        app.add_middleware(RemovedDirectRoutesGuard)
        register_removed_route("mlx_module", "/chat", "/mlx")

        with caplog.at_level(logging.WARNING, logger="core.middleware"):
            with TestClient(app, raise_server_exceptions=False) as client:
                client.post("/mlx/chat", json={})

        # Buscar el log de seguretat
        security_logs = [r for r in caplog.records if "direct_access_blocked" in r.getMessage()]
        assert security_logs, "No s'ha emès cap log security.plugin.direct_access_blocked"

        record = security_logs[0]
        assert hasattr(record, "plugin_name") and record.plugin_name == "mlx_module"
        assert hasattr(record, "route") and record.route == "/chat"
        assert hasattr(record, "full_route") and record.full_route == "/mlx/chat"
        assert hasattr(record, "client_ip")
        assert hasattr(record, "user_agent")


# ──────────────────────────────────────────────────────────────────────────
# Test 9: Path-param matching
# ──────────────────────────────────────────────────────────────────────────

class TestPathParamMatching:
    """La guarda ha de suportar rutes amb path params ({id}, etc.)."""

    def test_path_param_matching_in_removed_route(self):
        """removed=["/things/{id}"] → GET /things/42 retorna 403."""
        from core.middleware import register_removed_route, RemovedDirectRoutesGuard

        app = FastAPI()
        app.add_middleware(RemovedDirectRoutesGuard)
        register_removed_route("fake_plugin", "/things/{id}", "/fake")

        with TestClient(app, raise_server_exceptions=False) as client:
            r = client.get("/fake/things/42")

        assert r.status_code == 403
        body = r.json()
        assert body["error"] == "direct_plugin_endpoint_disabled"
        assert body["removed_route"] == "/fake/things/{id}"


# ──────────────────────────────────────────────────────────────────────────
# Test 10: Consistència TOML ↔ manifest.py
# ──────────────────────────────────────────────────────────────────────────

class TestGuardInternals:
    """Cobertura de branques internes del guard: idempotència i setup."""

    def test_register_removed_route_is_idempotent(self):
        """Registrar la mateixa ruta dues vegades no duplica l'entrada."""
        from core.middleware import register_removed_route, _REMOVED_ROUTE_REGISTRY, _REMOVED_ROUTE_PATTERNS

        register_removed_route("mlx_module", "/chat", "/mlx")
        register_removed_route("mlx_module", "/chat", "/mlx")  # duplicat → no-op

        assert len([k for k in _REMOVED_ROUTE_REGISTRY if k == "/mlx/chat"]) == 1
        assert len([p for p in _REMOVED_ROUTE_PATTERNS if p[3] == "/mlx/chat"]) == 1

    def test_setup_removed_direct_routes_guard_adds_middleware(self):
        """setup_removed_direct_routes_guard afegeix el middleware a l'app."""
        from core.middleware import setup_removed_direct_routes_guard, RemovedDirectRoutesGuard

        app = FastAPI()
        setup_removed_direct_routes_guard(app)

        mw_types = [type(m) for m in app.user_middleware]
        assert any(
            issubclass(t, RemovedDirectRoutesGuard) or t.__name__ == "RemovedDirectRoutesGuard"
            for t in mw_types
        ) or any(
            getattr(m, "cls", None) is RemovedDirectRoutesGuard
            for m in app.user_middleware
        ), "RemovedDirectRoutesGuard no s'ha afegit al middleware stack"


class TestTomlManifestConsistency:
    """El camp removed_direct_routes als TOMLs ha de coincidir amb el Python manifest.

    Prevé drift silenciós entre la documentació (TOML) i el runtime (manifest.py).
    """

    _PLUGINS = [
        ("mlx_module",      "mlx_module.manifest",      "/mlx"),
        ("llama_cpp_module", "llama_cpp_module.manifest", "/llama-cpp"),
        ("ollama_module",   "ollama_module.manifest",   "/ollama"),
    ]

    @pytest.mark.parametrize("plugin_name,manifest_import,_prefix", _PLUGINS)
    def test_toml_matches_python(self, plugin_name: str, manifest_import: str, _prefix: str):
        """El TOML i el manifest.py del plugin han de tenir removed_direct_routes idèntics."""
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib  # type: ignore[no-redef]

        import importlib

        toml_path = PROJECT_ROOT / "plugins" / plugin_name / "manifest.toml"
        with open(toml_path, "rb") as f:
            toml_data = tomllib.load(f)

        toml_routes = toml_data.get("module", {}).get("endpoints", {}).get(
            "removed_direct_routes", []
        )

        manifest = importlib.import_module(f"plugins.{manifest_import}")
        python_routes = getattr(manifest, "removed_direct_routes", [])

        assert sorted(toml_routes) == sorted(python_routes), (
            f"{plugin_name}: TOML removed_direct_routes={toml_routes!r} "
            f"però manifest.py removed_direct_routes={python_routes!r}. "
            f"Actualitza l'un o l'altre per evitar drift."
        )
