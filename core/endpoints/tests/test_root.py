"""
Tests per core/endpoints/root.py
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


def make_app(config=None, modules=None, i18n=None):
    app = FastAPI()
    app.state.config = config or {}
    app.state.modules = modules or {}
    app.state.i18n = i18n
    limiter = Limiter(key_func=get_remote_address)
    app.state.limiter = limiter
    app.add_middleware(SlowAPIMiddleware)
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    from core.endpoints.root import router
    app.include_router(router)
    return app


# ═══════════════════════════════════════════════════════════════════════════
# Tests de funcions pures
# ═══════════════════════════════════════════════════════════════════════════

class TestGetI18n:
    def test_get_i18n_without_state(self):
        from core.endpoints.root import get_i18n
        req = MagicMock()
        req.app.state = MagicMock(spec=[])  # sense atribut i18n
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


class TestRequiredModulesFromConfig:
    def test_empty_config(self):
        from core.endpoints.root import _required_modules_from_config
        result = _required_modules_from_config({})
        assert result == set()

    def test_enabled_modules(self):
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
        instance = MagicMock(spec=[])  # sense get_health ni health_check
        result = await _module_health_status(instance)
        assert result == "unknown"


# ═══════════════════════════════════════════════════════════════════════════
# Tests d'endpoints HTTP
# ═══════════════════════════════════════════════════════════════════════════

class TestRootEndpoint:
    def test_root_without_i18n(self):
        app = make_app()
        client = TestClient(app)
        resp = client.get("/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["system"] == "Nexe 0.8.5"
        assert data["version"] == "0.8.5"
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
        assert "uptime" in data

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
        """Sense mòduls requerits → healthy"""
        app = make_app(config={})
        client = TestClient(app)
        resp = client.get("/health/ready")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert "timestamp" in data

    def test_readiness_required_modules_present_healthy(self):
        """Mòdul requerit present i healthy → healthy"""
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
        """Mòdul requerit absent → unhealthy"""
        config = {"plugins": {"models": {"preferred_engine": "ollama"}}}
        app = make_app(config=config, modules={})
        client = TestClient(app)
        resp = client.get("/health/ready")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "unhealthy"

    def test_readiness_unhealthy_module(self):
        """Mòdul present però unhealthy → unhealthy"""
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
        """Mòdul degraded → degraded"""
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
        """Mòdul amb status unknown → degraded"""
        mock_module = MagicMock(spec=[])  # sense get_health ni health_check
        config = {"plugins": {"models": {"preferred_engine": "ollama"}}}
        modules = {"ollama_module": mock_module}
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
        assert data["name"] == "Nexe 0.8.5"
        assert data["version"] == "0.8.5"
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


class TestStatusEndpoint:
    def test_status_basic(self):
        app = make_app()
        client = TestClient(app)
        resp = client.get("/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "engine" in data
        assert "configured_engine" in data
        assert "modules_loaded" in data
        assert "engines_available" in data

    def test_status_with_mlx_node(self):
        """MLX amb _node → mlx_available=True"""
        mock_mlx = MagicMock()
        mock_mlx._node = MagicMock()  # node actiu
        modules = {"mlx_module": mock_mlx}
        app = make_app(modules=modules)
        client = TestClient(app)
        with patch.dict("os.environ", {"NEXE_MODEL_ENGINE": "mlx"}):
            resp = client.get("/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["engines_available"]["mlx"] is True

    def test_status_with_mlx_no_node(self):
        """MLX sense _node → mlx_available=False, fallback ollama"""
        mock_mlx = MagicMock()
        mock_mlx._node = None
        modules = {"mlx_module": mock_mlx}
        app = make_app(modules=modules)
        client = TestClient(app)
        with patch.dict("os.environ", {"NEXE_MODEL_ENGINE": "mlx"}):
            resp = client.get("/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["engines_available"]["mlx"] is False
        assert data["engine"] == "ollama"  # fallback

    def test_status_with_llama_cpp(self):
        """llama_cpp present → llama_cpp_available=True"""
        mock_llama = MagicMock()
        modules = {"llama_cpp_module": mock_llama}
        app = make_app(modules=modules)
        client = TestClient(app)
        resp = client.get("/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["engines_available"]["llama_cpp"] is True

    def test_status_with_ollama(self):
        """ollama present → ollama_available=True"""
        mock_ollama = MagicMock()
        modules = {"ollama_module": mock_ollama}
        app = make_app(modules=modules)
        client = TestClient(app)
        resp = client.get("/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["engines_available"]["ollama"] is True

    def test_status_llama_cpp_configured_but_missing(self):
        """llama_cpp configurat però no disponible → fallback ollama"""
        app = make_app()
        client = TestClient(app)
        with patch.dict("os.environ", {"NEXE_MODEL_ENGINE": "llama_cpp"}):
            resp = client.get("/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["engine"] == "ollama"


class TestCircuitStatusEndpoint:
    def test_circuit_status(self):
        app = make_app()
        client = TestClient(app)
        resp = client.get("/health/circuits")
        assert resp.status_code == 200
        data = resp.json()
        assert "circuits" in data
        assert isinstance(data["circuits"], list)
        assert len(data["circuits"]) == 3
        assert "timestamp" in data
