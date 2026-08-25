"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/test_removed_direct_routes_guard.py
Description: Follow-up F4.2 — RemovedDirectRoutesGuard middleware tests.
             Verifies that routes declared in removed_direct_routes return
             403, that active Ollama routes are NOT affected (critical regression),
             and that the loader rejects plugins with a collision.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from pathlib import Path

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _discover_removed_routes() -> list[tuple[str, str, str]]:
    """(plugin_name, route, prefix) for every removed_direct_routes entry
    declared in plugins/*/manifest.toml (#936): read from the real
    declaration, not invented per test."""
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib  # type: ignore[no-redef]

    found = []
    for manifest_toml in sorted((PROJECT_ROOT / "plugins").glob("*/manifest.toml")):
        with open(manifest_toml, "rb") as f:
            data = tomllib.load(f)
        endpoints = data.get("module", {}).get("endpoints", {})
        prefix = endpoints.get("router_prefix", "")
        for route in endpoints.get("removed_direct_routes", []):
            found.append((manifest_toml.parent.name, route, prefix))
    return found


_REMOVED_ROUTES = _discover_removed_routes()
# Control d'abast (#936): si la descoberta els deixa de trobar, algun canvi
# al parsing o al manifest real l'ha deixat cec — no s'hi val enumerar
# a mà sense res que vigili que l'enumeració no s'encongeix.
_KNOWN_PLUGINS_WITH_REMOVED_ROUTES = {"llama_cpp_module", "mlx_module", "ollama_module"}


# ──────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _clear_guard_registry():
    """Clears the guard registry between tests to avoid contamination."""
    from core import middleware as mw
    mw._REMOVED_ROUTE_REGISTRY.clear()
    mw._REMOVED_ROUTE_PATTERNS.clear()
    yield
    mw._REMOVED_ROUTE_REGISTRY.clear()
    mw._REMOVED_ROUTE_PATTERNS.clear()


def _build_guarded_app(*blocked_routes: tuple) -> FastAPI:
    """Creates a minimal app with RemovedDirectRoutesGuard and the registered routes.

    Args:
        blocked_routes: Tuples (plugin_name, manifest_route, prefix) to block.
    """
    from core.middleware import register_removed_route, RemovedDirectRoutesGuard

    app = FastAPI()
    app.add_middleware(RemovedDirectRoutesGuard)

    for plugin_name, manifest_route, prefix in blocked_routes:
        register_removed_route(plugin_name, manifest_route, prefix)

    return app


# ──────────────────────────────────────────────────────────────────────────
# Tests 1-3: 403 for the 3 ghost routes
# ──────────────────────────────────────────────────────────────────────────

class TestBlockedRoutes:
    """Every route declared in a real plugins/*/manifest.toml
    removed_direct_routes must return 403 (#936)."""

    def test_the_discovery_still_finds_the_known_plugins(self):
        discovered = {p for p, _route, _prefix in _REMOVED_ROUTES}
        missing = _KNOWN_PLUGINS_WITH_REMOVED_ROUTES - discovered
        assert not missing, f"la descoberta de removed_direct_routes ja no troba: {missing}"

    @pytest.mark.parametrize(
        "plugin_name,route,prefix", _REMOVED_ROUTES,
        ids=[p for p, _route, _prefix in _REMOVED_ROUTES],
    )
    def test_removed_route_returns_403(self, plugin_name, route, prefix):
        """POST <prefix><route> → 403 with error code direct_plugin_endpoint_disabled,
        for the exact route the plugin's own manifest.toml declares removed."""
        app = _build_guarded_app((plugin_name, route, prefix))
        full_route = f"{prefix}{route}"
        with TestClient(app, raise_server_exceptions=False) as client:
            r = client.post(full_route, json={})
        assert r.status_code == 403
        body = r.json()
        assert body["error"] == "direct_plugin_endpoint_disabled"
        assert body["removed_route"] == full_route


# ──────────────────────────────────────────────────────────────────────────
# Tests 4-5: CRITICAL REGRESSION — active Ollama routes NOT affected
# ──────────────────────────────────────────────────────────────────────────

class TestOllamaRegressions:
    """Active Ollama routes /api/pull and DELETE /api/models/{name}
    must NOT be affected by the guard."""

    def _build_ollama_app(self) -> FastAPI:
        from core.middleware import register_removed_route, RemovedDirectRoutesGuard
        from fastapi.responses import JSONResponse

        app = FastAPI()
        app.add_middleware(RemovedDirectRoutesGuard)
        register_removed_route("ollama_module", "/api/chat", "/ollama")

        # Simulated active routes (no real Ollama dependency)
        @app.post("/ollama/api/pull")
        async def pull_model():
            return JSONResponse({"status": "ok", "action": "pull"})

        @app.delete("/ollama/api/models/{model_name}")
        async def delete_model(model_name: str):
            return JSONResponse({"status": "ok", "model": model_name})

        return app

    def test_ollama_api_pull_still_works(self):
        """CRITICAL REGRESSION: POST /ollama/api/pull must NOT return 403."""
        app = self._build_ollama_app()
        with TestClient(app, raise_server_exceptions=False) as client:
            r = client.post("/ollama/api/pull", json={"name": "llama3"})
        assert r.status_code != 403 or r.json().get("error") != "direct_plugin_endpoint_disabled", (
            "REGRESSION: /ollama/api/pull blocked by the guard — implementation is incorrect"
        )
        assert r.status_code == 200

    def test_ollama_api_models_delete_still_works(self):
        """CRITICAL REGRESSION: DELETE /ollama/api/models/foo must NOT return 403."""
        app = self._build_ollama_app()
        with TestClient(app, raise_server_exceptions=False) as client:
            r = client.delete("/ollama/api/models/llama3")
        assert r.status_code != 403 or r.json().get("error") != "direct_plugin_endpoint_disabled", (
            "REGRESSION: DELETE /ollama/api/models/foo blocked by the guard"
        )
        assert r.status_code == 200


# ──────────────────────────────────────────────────────────────────────────
# Test 6: Canonical pipeline NOT affected
# ──────────────────────────────────────────────────────────────────────────

class TestPipelineNotAffected:
    """Canonical pipeline endpoints must not be blocked."""

    def test_pipeline_endpoints_still_work(self):
        """POST /ui/chat and /v1/chat/completions must NOT return 403 from the guard."""
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

        assert r_ui.status_code == 200, f"Pipeline /ui/chat affected by the guard: {r_ui.status_code}"
        assert r_v1.status_code == 200, f"Pipeline /v1/chat/completions affected: {r_v1.status_code}"


# ──────────────────────────────────────────────────────────────────────────
# Test 7: Loader fail-fast — collision removed_direct_routes ↔ registered router
# ──────────────────────────────────────────────────────────────────────────

class TestLoaderFailFast:
    """The loader must reject a plugin that declares removed_direct_routes
    and also registers the same route."""

    def test_plugin_with_colliding_route_is_rejected(self):
        """Fake plugin declares removed=["/foo"] and registers @router.post("/foo")
        → PluginLoadError with plugin_name and colliding_route."""
        from core.modules.protocol import PluginLoadError
        from core.modules.module_manager import ModuleManager

        # Build a fake manifest_module
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
# Test 8: Structured log on blocked access
# ──────────────────────────────────────────────────────────────────────────

class TestLogging:
    """The guard must emit a structured log when blocking a request."""

    def test_log_entry_on_blocked_access(self, caplog):
        """A blocked call emits security.plugin.direct_access_blocked
        with the 5 structured fields."""
        import logging
        from core.middleware import register_removed_route, RemovedDirectRoutesGuard

        app = FastAPI()
        app.add_middleware(RemovedDirectRoutesGuard)
        register_removed_route("mlx_module", "/chat", "/mlx")

        with caplog.at_level(logging.WARNING, logger="core.middleware"):
            with TestClient(app, raise_server_exceptions=False) as client:
                client.post("/mlx/chat", json={})

        # Search for the security log
        security_logs = [r for r in caplog.records if "direct_access_blocked" in r.getMessage()]
        assert security_logs, "No security.plugin.direct_access_blocked log was emitted"

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
    """The guard must support routes with path params ({id}, etc.)."""

    def test_path_param_matching_in_removed_route(self):
        """removed=["/things/{id}"] → GET /things/42 returns 403."""
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
# Test 10: TOML ↔ manifest.py consistency
# ──────────────────────────────────────────────────────────────────────────

class TestGuardInternals:
    """Coverage of internal guard branches: idempotency and setup."""

    def test_register_removed_route_is_idempotent(self):
        """Registering the same route twice does not duplicate the entry."""
        from core.middleware import register_removed_route, _REMOVED_ROUTE_REGISTRY, _REMOVED_ROUTE_PATTERNS

        register_removed_route("mlx_module", "/chat", "/mlx")
        register_removed_route("mlx_module", "/chat", "/mlx")  # duplicate → no-op

        assert len([k for k in _REMOVED_ROUTE_REGISTRY if k == "/mlx/chat"]) == 1
        assert len([p for p in _REMOVED_ROUTE_PATTERNS if p[3] == "/mlx/chat"]) == 1

    def test_setup_removed_direct_routes_guard_adds_middleware(self):
        """setup_removed_direct_routes_guard adds the middleware to the app."""
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
        ), "RemovedDirectRoutesGuard was not added to the middleware stack"


class TestTomlManifestConsistency:
    """The removed_direct_routes field in TOMLs must match the Python manifest.

    Prevents silent drift between the documentation (TOML) and the runtime (manifest.py).
    """

    _PLUGINS = sorted({plugin_name for plugin_name, _route, _prefix in _REMOVED_ROUTES})

    @pytest.mark.parametrize("plugin_name", _PLUGINS)
    def test_toml_matches_python(self, plugin_name: str):
        """The TOML and the plugin's manifest.py must have identical removed_direct_routes."""
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

        manifest = importlib.import_module(f"plugins.{plugin_name}.manifest")
        python_routes = getattr(manifest, "removed_direct_routes", [])

        assert sorted(toml_routes) == sorted(python_routes), (
            f"{plugin_name}: TOML removed_direct_routes={toml_routes!r} "
            f"but manifest.py removed_direct_routes={python_routes!r}. "
            f"Update one or the other to avoid drift."
        )
