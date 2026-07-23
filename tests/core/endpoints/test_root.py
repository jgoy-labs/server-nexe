"""
Tests for core/endpoints/root.py
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, AsyncMock, patch
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.middleware import SlowAPIMiddleware
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler

# Q2.3: /status and /health/circuits now require X-API-Key (security fix).
# Use same pattern as the Bug #22 tests.
_TEST_KEY = "test-status-q23-key"
_HEADERS = {"X-API-Key": _TEST_KEY}


def make_app(config=None, modules=None, i18n=None, minimal_mode=False):
    app = FastAPI()
    app.state.config = config or {}
    app.state.modules = modules or {}
    app.state.i18n = i18n
    app.state.minimal_mode = minimal_mode
    limiter = Limiter(key_func=get_remote_address)
    app.state.limiter = limiter
    app.add_middleware(SlowAPIMiddleware)
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    from core.endpoints.root import router
    app.include_router(router)
    return app


# ═══════════════════════════════════════════════════════════════════════════
# Tests for pure functions
# ═══════════════════════════════════════════════════════════════════════════

class TestGetI18n:
    def test_get_i18n_without_state(self):
        from core.endpoints.root import get_i18n
        req = MagicMock()
        req.app.state = MagicMock(spec=[])  # without i18n attribute
        result = get_i18n(req)
        assert result is None

    def test_get_i18n_with_i18n(self):
        from core.endpoints.root import get_i18n
        mock_i18n = MagicMock()
        req = MagicMock()
        req.app.state.i18n = mock_i18n
        result = get_i18n(req)
        assert result is mock_i18n


class TestNormalizeEngine:
    def test_normalize_engine_empty_string(self):
        from core.endpoints.root import _normalize_engine
        assert _normalize_engine("") == ""

    def test_normalize_engine_none(self):
        from core.endpoints.root import _normalize_engine
        assert _normalize_engine(None) == ""

    def test_normalize_engine_llama_dot_cpp(self):
        from core.endpoints.root import _normalize_engine
        assert _normalize_engine("llama.cpp") == "llama_cpp"

    def test_normalize_engine_llama_dash_cpp(self):
        from core.endpoints.root import _normalize_engine
        assert _normalize_engine("llama-cpp") == "llama_cpp"

    def test_normalize_engine_llamacpp(self):
        from core.endpoints.root import _normalize_engine
        assert _normalize_engine("llamacpp") == "llama_cpp"

    def test_normalize_engine_ollama(self):
        from core.endpoints.root import _normalize_engine
        assert _normalize_engine("ollama") == "ollama"

    def test_normalize_engine_mlx(self):
        from core.endpoints.root import _normalize_engine
        assert _normalize_engine("MLX") == "mlx"

    def test_normalize_engine_strips_whitespace(self):
        from core.endpoints.root import _normalize_engine
        assert _normalize_engine("  ollama  ") == "ollama"


class TestResolveEngineNodeAware:
    """B260 (consolidates the ex-B075-C6 TestResolveEffectiveEngine): /status and
    chat now share ONE resolver. The deleted _resolve_effective_engine is gone;
    these cases exercise the canonical routing._resolve_engine directly. Same
    priority order (explicit > config preferred > mlx→llama_cpp→ollama cascade),
    node-aware at the single source of truth.
    """

    def _resolve(self, preferred, *, mlx=False, llama=False, ollama=False):
        # Build the app_state the canonical resolver consumes. `preferred` is fed
        # via NEXE_MODEL_ENGINE (env-shadows-config), exactly as production does;
        # "auto"/"" mean "no preference" → cascade. A live node is modelled with a
        # non-None _node; an absent module models an unavailable engine.
        from core.endpoints.chat_engines.routing import _resolve_engine
        modules = {}
        if mlx:
            m = MagicMock(); m._node = MagicMock(); modules["mlx_module"] = m
        if llama:
            m = MagicMock(); m._node = MagicMock(); modules["llama_cpp_module"] = m
        if ollama:
            modules["ollama_module"] = MagicMock()
        app_state = MagicMock()
        app_state.modules = modules
        app_state.config = {}
        with patch.dict("os.environ", {"NEXE_MODEL_ENGINE": preferred}):
            engine, _ = _resolve_engine(None, app_state)
        return engine

    def test_auto_resolves_cascade_to_mlx(self):
        assert self._resolve("auto", mlx=True, ollama=True) == "mlx"

    def test_auto_resolves_cascade_to_ollama_when_only_ollama(self):
        assert self._resolve("auto", ollama=True) == "ollama"

    def test_empty_preferred_resolves_cascade(self):
        assert self._resolve("", mlx=True, ollama=True) == "mlx"

    def test_preferred_available_wins(self):
        assert self._resolve("mlx", mlx=True, ollama=True) == "mlx"

    def test_preferred_dead_engine_falls_through_to_cascade(self):
        # The crux: plain _resolve_engine would return "mlx" (no node check);
        # node-aware resolution reports what the user actually gets: ollama.
        assert self._resolve("mlx", mlx=False, ollama=True) == "ollama"

    def test_preferred_wins_over_cascade_order(self):
        # preferred=ollama must WIN over the cascade, which would pick llama_cpp
        # first (mlx→llama_cpp→ollama). Isolates the preferred branch.
        assert self._resolve("ollama", llama=True, ollama=True) == "ollama"

    def test_preferred_unavailable_falls_to_cascade(self):
        assert self._resolve("mlx", llama=True, ollama=True) == "llama_cpp"

    def test_normalizes_engine_aliases(self):
        assert self._resolve("llama.cpp", llama=True, ollama=True) == "llama_cpp"

    def test_nothing_available_defaults_ollama(self):
        assert self._resolve("auto") == "ollama"


class TestRequiredModulesFromConfig:
    def test_empty_config(self):
        from core.endpoints.root import _required_modules_from_config
        result = _required_modules_from_config({})
        assert result == set()

    def test_enabled_modules(self, monkeypatch):
        # Isolate from environment pollution: NEXE_APPROVED_MODULES may be set
        # by other tests/fixtures and causes an empty intersection.
        monkeypatch.delenv("NEXE_APPROVED_MODULES", raising=False)
        from core.endpoints.root import _required_modules_from_config
        config = {"plugins": {"modules": {"enabled": ["security_module", "rag_module"]}}}
        result = _required_modules_from_config(config)
        assert "security_module" in result
        assert "rag_module" in result

    def test_preferred_engine_ollama(self):
        from core.endpoints.root import _required_modules_from_config
        config = {"plugins": {"models": {"preferred_engine": "ollama"}}}
        result = _required_modules_from_config(config)
        assert "ollama_module" in result

    def test_preferred_engine_mlx(self):
        from core.endpoints.root import _required_modules_from_config
        config = {"plugins": {"models": {"preferred_engine": "mlx"}}}
        result = _required_modules_from_config(config)
        assert "mlx_module" in result

    def test_preferred_engine_llama_cpp(self):
        from core.endpoints.root import _required_modules_from_config
        config = {"plugins": {"models": {"preferred_engine": "llama_cpp"}}}
        result = _required_modules_from_config(config)
        assert "llama_cpp_module" in result

    def test_unknown_engine_not_added(self):
        from core.endpoints.root import _required_modules_from_config
        config = {"plugins": {"models": {"preferred_engine": "unknown_engine"}}}
        result = _required_modules_from_config(config)
        assert result == set()


class TestModuleHealthStatus:
    @pytest.mark.asyncio
    async def test_with_get_health_method(self):
        from core.endpoints.root import _module_health_status
        instance = MagicMock()
        instance.get_health.return_value = {"status": "healthy"}
        result = await _module_health_status(instance)
        assert result == "healthy"

    @pytest.mark.asyncio
    async def test_with_get_health_raises_exception(self):
        from core.endpoints.root import _module_health_status
        instance = MagicMock()
        instance.get_health.side_effect = Exception("error")
        result = await _module_health_status(instance)
        assert result == "unhealthy"

    @pytest.mark.asyncio
    async def test_with_health_check_method(self):
        from core.endpoints.root import _module_health_status
        instance = MagicMock(spec=["health_check"])
        mock_result = MagicMock()
        mock_result.status.value = "healthy"
        instance.health_check = AsyncMock(return_value=mock_result)
        result = await _module_health_status(instance)
        assert result == "healthy"

    @pytest.mark.asyncio
    async def test_with_health_check_raises_exception(self):
        from core.endpoints.root import _module_health_status
        instance = MagicMock(spec=["health_check"])
        instance.health_check = AsyncMock(side_effect=Exception("error"))
        result = await _module_health_status(instance)
        assert result == "unhealthy"

    @pytest.mark.asyncio
    async def test_with_neither_method(self):
        from core.endpoints.root import _module_health_status
        instance = MagicMock(spec=[])  # without get_health or health_check
        result = await _module_health_status(instance)
        assert result == "unknown"


# ═══════════════════════════════════════════════════════════════════════════
# Tests for HTTP endpoints
# ═══════════════════════════════════════════════════════════════════════════

class TestRootEndpoint:
    def test_root_without_i18n(self):
        app = make_app()
        client = TestClient(app)
        resp = client.get("/")
        assert resp.status_code == 200
        data = resp.json()
        from core.version import __version__
        assert data["system"] == f"Nexe {__version__}"
        assert data["version"] == __version__
        assert "description" in data
        assert "status" in data

    def test_root_with_i18n(self):
        mock_i18n = MagicMock()
        mock_i18n.t.side_effect = lambda key: f"translated:{key}"
        app = make_app(i18n=mock_i18n)
        client = TestClient(app)
        resp = client.get("/")
        assert resp.status_code == 200
        data = resp.json()
        assert "translated:" in data["description"]


class TestHealthEndpoint:
    def test_health_without_i18n(self):
        app = make_app()
        client = TestClient(app)
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data
        assert "message" in data
        assert "version" in data
        # B075-C1: uptime is real whole seconds since startup, not the old fixed
        # "operational" label. Mutation (revert to the label) → isdigit() False.
        assert data["uptime"].isdigit(), f"uptime must be whole seconds, got {data['uptime']!r}"
        assert int(data["uptime"]) >= 0

    def test_health_with_i18n(self):
        mock_i18n = MagicMock()
        mock_i18n.t.side_effect = lambda key: f"t:{key}"
        app = make_app(i18n=mock_i18n)
        client = TestClient(app)
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"].startswith("t:")


class TestReadinessEndpoint:
    def test_readiness_no_required_modules(self):
        """No required modules → healthy"""
        app = make_app(config={})
        client = TestClient(app)
        resp = client.get("/health/ready")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert "timestamp" in data

    def test_readiness_required_modules_present_healthy(self):
        """Required module present and healthy → healthy"""
        mock_module = MagicMock()
        mock_module.get_health.return_value = {"status": "healthy"}
        config = {"plugins": {"models": {"preferred_engine": "ollama"}}}
        modules = {"ollama_module": mock_module}
        app = make_app(config=config, modules=modules)
        client = TestClient(app)
        resp = client.get("/health/ready")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"

    def test_readiness_missing_module(self):
        """Required module absent → unhealthy"""
        config = {"plugins": {"models": {"preferred_engine": "ollama"}}}
        app = make_app(config=config, modules={})
        client = TestClient(app)
        resp = client.get("/health/ready")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "unhealthy"

    def test_readiness_unhealthy_module(self):
        """Module present but unhealthy → unhealthy"""
        mock_module = MagicMock()
        mock_module.get_health.return_value = {"status": "unhealthy"}
        config = {"plugins": {"models": {"preferred_engine": "ollama"}}}
        modules = {"ollama_module": mock_module}
        app = make_app(config=config, modules=modules)
        client = TestClient(app)
        resp = client.get("/health/ready")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "unhealthy"

    def test_readiness_degraded_module(self):
        """Degraded module → degraded"""
        mock_module = MagicMock()
        mock_module.get_health.return_value = {"status": "degraded"}
        config = {"plugins": {"models": {"preferred_engine": "ollama"}}}
        modules = {"ollama_module": mock_module}
        app = make_app(config=config, modules=modules)
        client = TestClient(app)
        resp = client.get("/health/ready")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "degraded"

    def test_readiness_unknown_module(self):
        """Module with unknown status → degraded"""
        mock_module = MagicMock(spec=[])  # without get_health or health_check
        config = {"plugins": {"models": {"preferred_engine": "ollama"}}}
        modules = {"ollama_module": mock_module}
        app = make_app(config=config, modules=modules)
        client = TestClient(app)
        resp = client.get("/health/ready")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "degraded"

    def test_readiness_engine_degraded_via_health_check_async(self):
        """Required module returning DEGRADED via async health_check() → readiness 'degraded' (not 'unhealthy').
        Regression guard for BUG #5: ollama_module returned UNHEALTHY when Ollama did not start."""
        from unittest.mock import AsyncMock as _AsyncMock

        mock_module = MagicMock(spec=["health_check"])
        mock_result = MagicMock()
        mock_result.status.value = "degraded"
        mock_module.health_check = _AsyncMock(return_value=mock_result)

        config = {"plugins": {"models": {"preferred_engine": "ollama"}}}
        modules = {"ollama_module": mock_module}
        app = make_app(config=config, modules=modules)
        client = TestClient(app)
        resp = client.get("/health/ready")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "degraded", (
            "Engine module DEGRADED (backend unavailable) must give readiness 'degraded', not 'unhealthy'"
        )

    def test_readiness_mixed_degraded_and_healthy_gives_degraded(self, monkeypatch):
        """One DEGRADED module + one HEALTHY → readiness 'degraded'.
        Isolates NEXE_APPROVED_MODULES to ensure 'security' is not filtered out in CI."""
        from unittest.mock import AsyncMock as _AsyncMock
        monkeypatch.delenv("NEXE_APPROVED_MODULES", raising=False)

        mock_ollama = MagicMock(spec=["health_check"])
        mock_res_degraded = MagicMock()
        mock_res_degraded.status.value = "degraded"
        mock_ollama.health_check = _AsyncMock(return_value=mock_res_degraded)

        mock_security = MagicMock()
        mock_security.get_health.return_value = {"status": "healthy"}

        config = {
            "plugins": {
                "models": {"preferred_engine": "ollama"},
                "modules": {"enabled": ["security"]},
            }
        }
        modules = {"ollama_module": mock_ollama, "security": mock_security}
        app = make_app(config=config, modules=modules)
        client = TestClient(app)
        resp = client.get("/health/ready")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "degraded"


class TestApiInfoEndpoint:
    def test_api_info_without_i18n(self):
        app = make_app()
        client = TestClient(app)
        resp = client.get("/api/info")
        assert resp.status_code == 200
        data = resp.json()
        from core.version import __version__
        assert data["name"] == f"Nexe {__version__}"
        assert data["version"] == __version__
        assert isinstance(data["endpoints"], list)
        assert len(data["endpoints"]) == 3

    def test_api_info_with_i18n(self):
        mock_i18n = MagicMock()
        mock_i18n.t.side_effect = lambda key: f"t:{key}"
        app = make_app(i18n=mock_i18n)
        client = TestClient(app)
        resp = client.get("/api/info")
        assert resp.status_code == 200
        data = resp.json()
        assert "t:" in data["description"]

    def test_api_info_summary_does_not_promise_exhaustiveness(self):
        """B075-C2: /api/info returns a curated 3-endpoint subset, so its summary
        must not claim to be the full 'list of available endpoints' (40+ routes).
        Mutation: restore that summary → this assert fails."""
        app = make_app()
        route = next(
            r for r in app.routes
            if getattr(r, "path", None) == "/api/info"
        )
        summary = (route.summary or "").lower()
        assert "list of available endpoints" not in summary, (
            "summary over-promises an exhaustive endpoint list"
        )
        assert "subset" in summary, "summary should signal the list is a subset"


class TestStatusEndpoint:
    @pytest.fixture(autouse=True)
    def _setup_api_key(self, monkeypatch):
        """Q2.3: /status now requires X-API-Key. Configure key for tests."""
        monkeypatch.setenv("NEXE_PRIMARY_API_KEY", _TEST_KEY)
        monkeypatch.delenv("NEXE_PRIMARY_KEY_EXPIRES", raising=False)
        monkeypatch.setenv("NEXE_DEV_MODE", "false")

    def test_status_basic(self):
        app = make_app()
        client = TestClient(app)
        resp = client.get("/status", headers=_HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert "engine" in data
        assert "configured_engine" in data
        assert "modules_loaded" in data
        assert "engines_available" in data

    def test_status_with_mlx_node(self):
        """MLX with _node → mlx_available=True"""
        mock_mlx = MagicMock()
        mock_mlx._node = MagicMock()  # active node
        modules = {"mlx_module": mock_mlx}
        app = make_app(modules=modules)
        client = TestClient(app)
        with patch.dict("os.environ", {"NEXE_MODEL_ENGINE": "mlx"}):
            resp = client.get("/status", headers=_HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert data["engines_available"]["mlx"] is True

    def test_status_with_mlx_no_node(self):
        """MLX without _node → mlx_available=False, fallback ollama"""
        mock_mlx = MagicMock()
        mock_mlx._node = None
        modules = {"mlx_module": mock_mlx}
        app = make_app(modules=modules)
        client = TestClient(app)
        with patch.dict("os.environ", {"NEXE_MODEL_ENGINE": "mlx"}):
            resp = client.get("/status", headers=_HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert data["engines_available"]["mlx"] is False
        assert data["engine"] == "ollama"  # fallback to ollama

    def test_status_with_llama_cpp(self):
        """llama_cpp present → llama_cpp_available=True"""
        mock_llama = MagicMock()
        modules = {"llama_cpp_module": mock_llama}
        app = make_app(modules=modules)
        client = TestClient(app)
        resp = client.get("/status", headers=_HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert data["engines_available"]["llama_cpp"] is True

    def test_status_with_ollama(self):
        """ollama present → ollama_available=True"""
        mock_ollama = MagicMock()
        modules = {"ollama_module": mock_ollama}
        app = make_app(modules=modules)
        client = TestClient(app)
        resp = client.get("/status", headers=_HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert data["engines_available"]["ollama"] is True

    def test_status_llama_cpp_configured_but_missing(self):
        """llama_cpp configured but unavailable → fallback ollama"""
        app = make_app()
        client = TestClient(app)
        with patch.dict("os.environ", {"NEXE_MODEL_ENGINE": "llama_cpp"}):
            resp = client.get("/status", headers=_HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert data["engine"] == "ollama"

    def test_status_resolved_engine_auto_reports_concrete(self):
        """B075-C6: with env=auto and mlx alive, resolved_engine is the concrete
        engine chat will run — not the literal 'auto' the legacy field keeps."""
        mock_mlx = MagicMock()
        mock_mlx._node = MagicMock()  # live node
        mock_ollama = MagicMock()
        app = make_app(modules={"mlx_module": mock_mlx, "ollama_module": mock_ollama})
        client = TestClient(app)
        with patch.dict("os.environ", {"NEXE_MODEL_ENGINE": "auto"}):
            resp = client.get("/status", headers=_HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert data["resolved_engine"] == "mlx"
        assert data["engine"] == "auto"  # legacy field unchanged (backward-compat)

    def test_status_resolved_engine_node_aware_with_dead_node(self):
        """B260: explicit mlx with a DEAD node resolves to ollama (node-aware), and
        /status stays in lockstep with the canonical resolver even under a dead
        node — parity asserted DYNAMICALLY against _resolve_engine, not a literal."""
        from core.endpoints.chat_engines.routing import _resolve_engine
        mock_mlx = MagicMock()
        mock_mlx._node = None  # ghost module: key present, node dead
        mock_ollama = MagicMock()
        app = make_app(modules={"mlx_module": mock_mlx, "ollama_module": mock_ollama})
        client = TestClient(app)
        with patch.dict("os.environ", {"NEXE_MODEL_ENGINE": "mlx"}):
            resp = client.get("/status", headers=_HEADERS)
            router_choice, _ = _resolve_engine(None, app.state)
        assert resp.status_code == 200
        assert resp.json()["resolved_engine"] == router_choice == "ollama"

    def test_status_resolved_engine_honors_config_preferred_when_env_unset(self, monkeypatch):
        """B075-C6: when NEXE_MODEL_ENGINE is unset, resolved_engine honors the
        config preferred_engine (the legacy ad-hoc field ignored it entirely)."""
        # preferred=ollama must win over the cascade (which picks llama_cpp first),
        # proving /status actually reads config preferred_engine via the canonical
        # _get_preferred_engine path.
        monkeypatch.delenv("NEXE_MODEL_ENGINE", raising=False)
        config = {"plugins": {"models": {"preferred_engine": "ollama"}}}
        mock_llama = MagicMock()
        mock_ollama = MagicMock()
        app = make_app(config=config, modules={"llama_cpp_module": mock_llama, "ollama_module": mock_ollama})
        client = TestClient(app)
        resp = client.get("/status", headers=_HEADERS)
        assert resp.status_code == 200
        assert resp.json()["resolved_engine"] == "ollama"

    def test_status_resolved_engine_env_auto_shadows_config_preferred(self):
        """B075-C6 regression guard: env=auto SHADOWS config preferred_engine —
        the chat router ignores config when env is set, so resolved_engine must
        too (cascade), NOT silently honour config. This is the exact divergence
        the field was meant to eliminate."""
        config = {"plugins": {"models": {"preferred_engine": "ollama"}}}
        # mlx dead, llama_cpp + ollama alive: chat resolves "llama_cpp" (cascade);
        # honouring config would wrongly give "ollama".
        mock_mlx = MagicMock(); mock_mlx._node = None
        mock_llama = MagicMock()
        mock_ollama = MagicMock()
        app = make_app(config=config, modules={
            "mlx_module": mock_mlx, "llama_cpp_module": mock_llama, "ollama_module": mock_ollama,
        })
        client = TestClient(app)
        with patch.dict("os.environ", {"NEXE_MODEL_ENGINE": "auto"}):
            resp = client.get("/status", headers=_HEADERS)
        assert resp.status_code == 200
        assert resp.json()["resolved_engine"] == "llama_cpp"

    def test_status_resolved_engine_parity_with_router_when_nodes_live(self):
        """B075-C6 anti-drift: when every module has a live node (node-aware ==
        key-presence), resolved_engine must MATCH the canonical chat resolver
        _resolve_engine(None, app_state) string exactly."""
        from core.endpoints.chat_engines.routing import _resolve_engine
        mock_mlx = MagicMock(); mock_mlx._node = MagicMock()
        mock_ollama = MagicMock()
        app = make_app(modules={"mlx_module": mock_mlx, "ollama_module": mock_ollama})
        client = TestClient(app)
        with patch.dict("os.environ", {"NEXE_MODEL_ENGINE": "auto"}):
            resp = client.get("/status", headers=_HEADERS)
            router_choice, _ = _resolve_engine(None, app.state)
        assert resp.status_code == 200
        assert resp.json()["resolved_engine"] == router_choice

    def test_status_without_api_key_returns_401(self, monkeypatch):
        """Q2.3 anti-regression: /status without X-API-Key must return 401."""
        # Use the autouse fixture key but DON'T send the header
        app = make_app()
        client = TestClient(app)
        resp = client.get("/status")  # no headers
        assert resp.status_code == 401

    def test_status_with_invalid_api_key_returns_401(self):
        """Q2.3 anti-regression: /status with wrong key returns 401."""
        app = make_app()
        client = TestClient(app)
        resp = client.get("/status", headers={"X-API-Key": "wrong-key"})
        assert resp.status_code == 401


class TestCircuitStatusEndpoint:
    @pytest.fixture(autouse=True)
    def _setup_api_key(self, monkeypatch):
        """Q2.3: /health/circuits now requires X-API-Key."""
        monkeypatch.setenv("NEXE_PRIMARY_API_KEY", _TEST_KEY)
        monkeypatch.delenv("NEXE_PRIMARY_KEY_EXPIRES", raising=False)
        monkeypatch.setenv("NEXE_DEV_MODE", "false")

    def test_circuit_status(self):
        app = make_app()
        client = TestClient(app)
        resp = client.get("/health/circuits", headers=_HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert "circuits" in data
        assert isinstance(data["circuits"], list)
        # WS7-01: ollama is the only wired breaker (qdrant/http were
        # decorative and always reported closed — removed)
        assert len(data["circuits"]) == 1
        assert data["circuits"][0]["name"] == "ollama"
        assert "timestamp" in data

    def test_circuit_status_without_api_key_returns_401(self):
        """Q2.3 anti-regression: /health/circuits without X-API-Key returns 401."""
        app = make_app()
        client = TestClient(app)
        resp = client.get("/health/circuits")
        assert resp.status_code == 401
