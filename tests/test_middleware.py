"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy
Location: tests/test_middleware.py
Description: Tests per core/middleware.py (CORS, rate limiting, CSRF, etc.)

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import os
import pytest
from fastapi import FastAPI
from unittest.mock import MagicMock, patch


class TestTranslateHelper:

    def test_with_no_i18n_returns_fallback(self):
        from core.middleware import _translate
        result = _translate(None, "some.key", "fallback text")
        assert result == "fallback text"

    def test_with_no_i18n_and_kwargs_formats(self):
        from core.middleware import _translate
        result = _translate(None, "some.key", "Error: {error}", error="test error")
        assert result == "Error: test error"

    def test_with_i18n_returns_translation(self):
        from core.middleware import _translate
        mock_i18n = MagicMock()
        mock_i18n.t = MagicMock(return_value="Translated text")
        result = _translate(mock_i18n, "some.key", "fallback")
        assert result == "Translated text"

    def test_with_i18n_missing_key_falls_back(self):
        from core.middleware import _translate
        mock_i18n = MagicMock()
        mock_i18n.t = MagicMock(return_value="some.key")  # Returns key = not translated
        result = _translate(mock_i18n, "some.key", "fallback text")
        assert result == "fallback text"


class TestSetupRateLimiting:

    def test_adds_middleware_to_app(self):
        from core.middleware import setup_rate_limiting
        app = FastAPI()
        setup_rate_limiting(app)
        assert hasattr(app.state, 'limiter')

    def test_with_i18n(self):
        from core.middleware import setup_rate_limiting
        app = FastAPI()
        mock_i18n = MagicMock()
        mock_i18n.t = MagicMock(return_value="test.key")
        setup_rate_limiting(app, i18n=mock_i18n)
        assert hasattr(app.state, 'limiter')

    def test_advanced_rate_limiting_setup(self):
        from core.middleware import setup_rate_limiting
        app = FastAPI()

        mock_limiter = MagicMock()
        mock_cleanup = MagicMock()

        with patch("core.middleware.ADVANCED_RATE_LIMITING", True), \
             patch("core.dependencies.limiter_by_key", mock_limiter), \
             patch("core.dependencies.limiter_composite", mock_limiter), \
             patch("core.dependencies.limiter_by_endpoint", mock_limiter), \
             patch("core.dependencies.start_rate_limit_cleanup_task", mock_cleanup):
            setup_rate_limiting(app)

        assert hasattr(app.state, 'limiter')

    def test_advanced_rate_limiting_exception_falls_back(self):
        from core.middleware import setup_rate_limiting
        app = FastAPI()

        with patch("core.middleware.ADVANCED_RATE_LIMITING", True), \
             patch("core.dependencies.limiter_by_key", side_effect=Exception("import error")):
            # Should not raise, just fall back
            setup_rate_limiting(app)


class TestSetupCors:

    def test_wildcard_raises_value_error(self):
        from core.middleware import setup_cors
        app = FastAPI()
        config = {"core": {"server": {"cors_origins": ["*"]}}}
        with pytest.raises(ValueError, match="wildcard"):
            setup_cors(app, config)

    def test_empty_origins_raises_value_error(self):
        from core.middleware import setup_cors
        app = FastAPI()
        config = {"core": {"server": {"cors_origins": []}}}
        with pytest.raises(ValueError):
            setup_cors(app, config)

    def test_valid_origins_adds_cors_middleware(self):
        from core.middleware import setup_cors
        app = FastAPI()
        config = {"core": {"server": {"cors_origins": ["http://localhost:3000"]}}}
        setup_cors(app, config)
        # Just verify no exception raised

    def test_security_logger_called_on_wildcard(self):
        from core.middleware import setup_cors
        app = FastAPI()
        mock_logger = MagicMock()
        app.state.security_logger = mock_logger
        config = {"core": {"server": {"cors_origins": ["*"]}}}
        with pytest.raises(ValueError):
            setup_cors(app, config)
        mock_logger.log_config_validation_failed.assert_called_once()

    def test_security_logger_called_on_empty_origins(self):
        from core.middleware import setup_cors
        app = FastAPI()
        mock_logger = MagicMock()
        app.state.security_logger = mock_logger
        config = {"core": {"server": {"cors_origins": []}}}
        with pytest.raises(ValueError):
            setup_cors(app, config)
        mock_logger.log_config_validation_failed.assert_called_once()

    def test_cors_with_custom_methods_and_headers(self):
        from core.middleware import setup_cors
        app = FastAPI()
        config = {
            "core": {
                "server": {
                    "cors_origins": ["http://localhost"],
                    "cors_methods": ["GET", "POST"],
                    "cors_headers": ["Content-Type"],
                }
            }
        }
        setup_cors(app, config)  # Should not raise


class TestSetupRequestSizeLimit:

    def test_adds_middleware(self):
        from core.middleware import setup_request_size_limit
        app = FastAPI()
        config = {}
        setup_request_size_limit(app, config)
        # Just verify no crash

    def test_custom_max_size_from_config(self):
        from core.middleware import setup_request_size_limit
        app = FastAPI()
        config = {"core": {"server": {"max_request_size": 1024}}}
        setup_request_size_limit(app, config)


class TestSetupPrometheusMetrics:

    def test_adds_middleware_when_available(self):
        from core.middleware import setup_prometheus_metrics
        app = FastAPI()
        setup_prometheus_metrics(app)

    def test_handles_import_error_gracefully(self):
        from core.middleware import setup_prometheus_metrics
        app = FastAPI()
        with patch("core.metrics.middleware.PrometheusMiddleware", side_effect=ImportError("not found")):
            # Should not raise
            setup_prometheus_metrics(app)


class TestSetupCsrfProtection:

    def test_dev_mode_no_crash(self, monkeypatch):
        from core.middleware import setup_csrf_protection
        app = FastAPI()
        monkeypatch.delenv("NEXE_CSRF_SECRET", raising=False)
        monkeypatch.delenv("NEXE_ENV", raising=False)
        config = {}
        setup_csrf_protection(app, config)

    def test_production_mode_logs_error(self, monkeypatch):
        from core.middleware import setup_csrf_protection
        app = FastAPI()
        monkeypatch.delenv("NEXE_CSRF_SECRET", raising=False)
        monkeypatch.setenv("NEXE_ENV", "production")
        config = {}
        setup_csrf_protection(app, config)

    def test_with_csrf_secret_configured(self, monkeypatch):
        from core.middleware import setup_csrf_protection
        app = FastAPI()
        monkeypatch.setenv("NEXE_CSRF_SECRET", "test-secret-abc123")
        config = {}
        setup_csrf_protection(app, config)

    def test_csrf_cookie_secure_override(self, monkeypatch):
        from core.middleware import setup_csrf_protection
        app = FastAPI()
        monkeypatch.setenv("NEXE_CSRF_SECRET", "test-secret")
        monkeypatch.setenv("NEXE_ENV", "production")
        config = {"core": {"server": {"csrf_cookie_secure": False, "host": "127.0.0.1"}}}
        setup_csrf_protection(app, config)

    def test_import_error_starlette_csrf_no_crash(self, monkeypatch):
        from core.middleware import setup_csrf_protection
        app = FastAPI()
        monkeypatch.setenv("NEXE_CSRF_SECRET", "test-secret")
        config = {}
        with patch.dict("sys.modules", {"starlette_csrf": None}):
            # Should not crash if starlette-csrf not installed
            setup_csrf_protection(app, config)


class TestSetupTrustedHosts:

    def test_default_config(self):
        from core.middleware import setup_trusted_hosts
        app = FastAPI()
        setup_trusted_hosts(app, {})

    def test_custom_host_added(self):
        from core.middleware import setup_trusted_hosts
        app = FastAPI()
        config = {"core": {"server": {"host": "192.168.1.100"}}}
        setup_trusted_hosts(app, config)

    def test_empty_host_ignored(self):
        from core.middleware import setup_trusted_hosts
        app = FastAPI()
        config = {"core": {"server": {"host": ""}}}
        setup_trusted_hosts(app, config)

    def test_0000_host_not_added(self):
        from core.middleware import setup_trusted_hosts
        app = FastAPI()
        config = {"core": {"server": {"host": "0.0.0.0"}}}
        setup_trusted_hosts(app, config)


class TestSetupAllMiddleware:

    def test_setup_all_middleware_success(self):
        from core.middleware import setup_all_middleware
        app = FastAPI()
        config = {"core": {"server": {"cors_origins": ["http://localhost"]}}}
        setup_all_middleware(app, config)

    def test_setup_all_middleware_with_i18n(self):
        from core.middleware import setup_all_middleware
        app = FastAPI()
        mock_i18n = MagicMock()
        mock_i18n.t = MagicMock(return_value="translated")
        config = {"core": {"server": {"cors_origins": ["http://localhost"]}}}
        setup_all_middleware(app, config, i18n=mock_i18n)
