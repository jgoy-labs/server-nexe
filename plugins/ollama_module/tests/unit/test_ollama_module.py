"""
Tests unitaris per plugins/ollama_module/module.py
"""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from plugins.ollama_module.module import OllamaModule, OLLAMA_CONNECTION_TIMEOUT


class TestOllamaModuleInit:
    def test_default_creation(self):
        module = OllamaModule()
        assert module.metadata.name == "ollama_module"
        assert module.metadata.version is not None
        assert "localhost" in module.base_url or module.base_url.startswith("http")

    def test_custom_base_url(self):
        with patch.dict("os.environ", {"NEXE_OLLAMA_HOST": "http://custom:11434/"}):
            module = OllamaModule()
        assert module.base_url == "http://custom:11434"  # sense trailing /

    def test_from_env_variable(self):
        with patch.dict("os.environ", {"NEXE_OLLAMA_HOST": "http://envhost:11434"}):
            module = OllamaModule()
        assert module.base_url == "http://envhost:11434"

    def test_with_i18n_set_after_init(self):
        mock_i18n = MagicMock()
        module = OllamaModule()
        module.i18n = mock_i18n
        assert module.i18n is mock_i18n

    def test_timeout_from_env(self):
        with patch.dict("os.environ", {"NEXE_OLLAMA_CHAT_TIMEOUT": "60.0"}):
            module = OllamaModule()
        assert module.timeout == 60.0


class TestOllamaModuleTranslate:
    def setup_method(self):
        self.module = OllamaModule()

    def test_t_without_i18n(self):
        result = self.module._t("key", "Fallback")
        assert result == "Fallback"

    def test_t_with_i18n_found(self):
        mock_i18n = MagicMock()
        mock_i18n.t.return_value = "Traduit"
        self.module.i18n = mock_i18n
        result = self.module._t("key", "Fallback")
        assert result == "Traduit"

    def test_t_with_i18n_key_not_found(self):
        mock_i18n = MagicMock()
        mock_i18n.t.side_effect = lambda k, **kw: k
        self.module.i18n = mock_i18n
        result = self.module._t("some.key", "Fallback")
        assert result == "Fallback"

    def test_t_with_i18n_exception(self):
        mock_i18n = MagicMock()
        mock_i18n.t.side_effect = Exception("error")
        self.module.i18n = mock_i18n
        result = self.module._t("key", "Fallback")
        assert result == "Fallback"

    def test_t_with_kwargs(self):
        result = self.module._t("key", "Count: {count}", count=5)
        assert result == "Count: 5"


class TestOllamaModuleCheckConnection:
    @pytest.mark.asyncio
    async def test_connection_success(self):
        module = OllamaModule()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await module.check_connection()
        assert result is True

    @pytest.mark.asyncio
    async def test_connection_failure_non_200(self):
        module = OllamaModule()
        mock_response = MagicMock()
        mock_response.status_code = 503
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await module.check_connection()
        assert result is False

    @pytest.mark.asyncio
    async def test_connection_circuit_open(self):
        from core.resilience import CircuitOpenError
        module = OllamaModule()
        with patch("httpx.AsyncClient", side_effect=CircuitOpenError("circuit open")):
            result = await module.check_connection()
        assert result is False

    @pytest.mark.asyncio
    async def test_connection_httpx_not_installed(self):
        """httpx és None → check_connection no pot funcionar"""
        module = OllamaModule()
        # El mòdul comprova si httpx és None al health_check però no al check_connection
        # Comprovem que el health_check retorna UNKNOWN si httpx és None
        with patch("plugins.ollama_module.module.httpx", None):
            from core.loader.protocol import HealthStatus
            result = await module.health_check()
        assert result.status == HealthStatus.UNKNOWN


class TestOllamaModuleHealthCheck:
    @pytest.mark.asyncio
    async def test_health_check_connected(self):
        from core.loader.protocol import HealthStatus
        module = OllamaModule()
        with patch.object(module, "check_connection", return_value=True):
            result = await module.health_check()
        assert result.status == HealthStatus.HEALTHY

    @pytest.mark.asyncio
    async def test_health_check_not_connected(self):
        from core.loader.protocol import HealthStatus
        module = OllamaModule()
        with patch.object(module, "check_connection", return_value=False):
            result = await module.health_check()
        assert result.status == HealthStatus.UNHEALTHY

    @pytest.mark.asyncio
    async def test_health_check_exception(self):
        from core.loader.protocol import HealthStatus
        module = OllamaModule()
        with patch.object(module, "check_connection", side_effect=Exception("error")):
            result = await module.health_check()
        assert result.status == HealthStatus.DEGRADED
