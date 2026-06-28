"""
────────────────────────────────────
Server Nexe
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
        # MC-103/MC-123/124: advanced limiters are gone; with the flag on,
        # setup just enforces the per-IP limiter (no orphan names to patch).
        from core.middleware import setup_rate_limiting
        app = FastAPI()
        with patch("core.middleware.ADVANCED_RATE_LIMITING", True):
            setup_rate_limiting(app)
        assert hasattr(app.state, 'limiter')


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
        mw_before = len(app.user_middleware)
        config = {"core": {"server": {"cors_origins": ["http://localhost:3000"]}}}
        setup_cors(app, config)
        assert len(app.user_middleware) > mw_before

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
        mw_before = len(app.user_middleware)
        config = {
            "core": {
                "server": {
                    "cors_origins": ["http://localhost"],
                    "cors_methods": ["GET", "POST"],
                    "cors_headers": ["Content-Type"],
                }
            }
        }
        setup_cors(app, config)
        assert len(app.user_middleware) > mw_before


class TestSetupRequestSizeLimit:

    def test_adds_middleware(self):
        from core.middleware import setup_request_size_limit
        app = FastAPI()
        mw_before = len(app.user_middleware)
        setup_request_size_limit(app, {})
        assert len(app.user_middleware) > mw_before

    def test_custom_max_size_from_config(self):
        from core.middleware import setup_request_size_limit
        app = FastAPI()
        mw_before = len(app.user_middleware)
        config = {"core": {"server": {"max_request_size": 1024}}}
        setup_request_size_limit(app, config)
        assert len(app.user_middleware) > mw_before


class TestSetupPrometheusMetrics:

    def test_adds_middleware_when_available(self):
        from core.middleware import setup_prometheus_metrics
        app = FastAPI()
        mw_before = len(app.user_middleware)
        setup_prometheus_metrics(app)
        assert len(app.user_middleware) >= mw_before

    def test_handles_import_error_gracefully(self, caplog):
        import logging
        from core.middleware import setup_prometheus_metrics
        app = FastAPI()
        mw_before = len(app.user_middleware)
        with patch.dict("sys.modules", {"core.metrics.middleware": None}):
            with caplog.at_level(logging.WARNING):
                setup_prometheus_metrics(app)
        assert any("prometheus" in r.message.lower() or "not_available" in r.message for r in caplog.records)


class TestSetupCsrfProtection:

    def test_dev_mode_uses_persistent_secret(self, monkeypatch, caplog, tmp_path):
        """F2.6 BUG-NB-3: without NEXE_CSRF_SECRET, the loader persists a
        stable secret on disk instead of regenerating one every boot."""
        import logging
        from core.middleware import setup_csrf_protection
        app = FastAPI()
        monkeypatch.delenv("NEXE_CSRF_SECRET", raising=False)
        monkeypatch.delenv("NEXE_ENV", raising=False)
        # Redirect ~/.nexe to tmp_path so the test does not pollute the dev home
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        mw_before = len(app.user_middleware)
        with caplog.at_level(logging.INFO, logger="core.middleware"):
            setup_csrf_protection(app, {})
        assert len(app.user_middleware) > mw_before
        assert (tmp_path / ".nexe" / "csrf_secret").exists(), (
            "F2.6 BUG-NB-3: dev mode must persist the secret to ~/.nexe/csrf_secret"
        )
        assert any(
            "persistent" in r.message.lower() or "persisted" in r.message.lower()
            for r in caplog.records
        )

    def test_production_without_secret_warns_and_persists(self, monkeypatch, caplog, tmp_path):
        """F2.6 BUG-NB-3: production without env still persists a fallback
        secret; the log is now a warning (sessions survive restarts) instead
        of an error (sessions invalidated)."""
        from core.middleware import setup_csrf_protection
        import logging
        app = FastAPI()
        monkeypatch.delenv("NEXE_CSRF_SECRET", raising=False)
        monkeypatch.setenv("NEXE_ENV", "production")
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        with caplog.at_level(logging.WARNING):
            setup_csrf_protection(app, {})
        assert any("production" in r.message.lower() for r in caplog.records)
        assert (tmp_path / ".nexe" / "csrf_secret").exists()

    def test_with_csrf_secret_adds_middleware(self, monkeypatch):
        from core.middleware import setup_csrf_protection
        app = FastAPI()
        monkeypatch.setenv("NEXE_CSRF_SECRET", "test-secret-abc123")
        mw_before = len(app.user_middleware)
        setup_csrf_protection(app, {})
        assert len(app.user_middleware) > mw_before

    def test_csrf_cookie_secure_override(self, monkeypatch):
        from core.middleware import setup_csrf_protection
        app = FastAPI()
        monkeypatch.setenv("NEXE_CSRF_SECRET", "test-secret")
        monkeypatch.setenv("NEXE_ENV", "production")
        mw_before = len(app.user_middleware)
        config = {"core": {"server": {"csrf_cookie_secure": False, "host": "127.0.0.1"}}}
        setup_csrf_protection(app, config)
        assert len(app.user_middleware) > mw_before


class TestSetupTrustedHosts:

    def test_default_config_adds_middleware(self):
        from core.middleware import setup_trusted_hosts
        app = FastAPI()
        mw_before = len(app.user_middleware)
        setup_trusted_hosts(app, {})
        assert len(app.user_middleware) > mw_before

    def test_custom_host_added(self):
        from core.middleware import setup_trusted_hosts
        app = FastAPI()
        mw_before = len(app.user_middleware)
        config = {"core": {"server": {"host": "192.168.1.100"}}}
        setup_trusted_hosts(app, config)
        assert len(app.user_middleware) > mw_before

    def test_empty_host_ignored(self):
        # T2 REFORÇAT: verifica que "" NO entra a l'allowlist de TrustedHostMiddleware.
        # Anti-DNS-rebinding: si la guarda de middleware.py:494 es trencava i "" s'afegia,
        # qualsevol Host header buit passaria la validació. El test ha de posar-se VERMELL
        # si la guarda desapareix.
        from core.middleware import setup_trusted_hosts
        from starlette.middleware.trustedhost import TrustedHostMiddleware
        app = FastAPI()
        config = {"core": {"server": {"host": ""}}}
        setup_trusted_hosts(app, config)
        trusted_mw = next(
            (mw for mw in app.user_middleware if mw.cls is TrustedHostMiddleware),
            None,
        )
        assert trusted_mw is not None, "TrustedHostMiddleware no s'ha afegit"
        allowed = trusted_mw.kwargs.get("allowed_hosts", [])
        assert "" not in allowed, (
            'Host buit ("") ha entrat a l\'allowlist de TrustedHost — risc de DNS rebinding'
        )

    def test_0000_host_not_added(self):
        # T2 REFORÇAT: verifica que "0.0.0.0" NO entra a l'allowlist de TrustedHostMiddleware.
        # Anti-DNS-rebinding: "0.0.0.0" és un wildcard d'interfície (bind-all); afegir-lo a
        # l'allowlist permetria qualsevol Host header i anularia la protecció. El test ha de
        # posar-se VERMELL si la guarda de middleware.py:494 desapareix.
        from core.middleware import setup_trusted_hosts
        from starlette.middleware.trustedhost import TrustedHostMiddleware
        app = FastAPI()
        config = {"core": {"server": {"host": "0.0.0.0"}}}
        setup_trusted_hosts(app, config)
        trusted_mw = next(
            (mw for mw in app.user_middleware if mw.cls is TrustedHostMiddleware),
            None,
        )
        assert trusted_mw is not None, "TrustedHostMiddleware no s'ha afegit"
        allowed = trusted_mw.kwargs.get("allowed_hosts", [])
        assert "0.0.0.0" not in allowed, (
            '"0.0.0.0" ha entrat a l\'allowlist de TrustedHost — anularia la protecció anti-DNS-rebinding'
        )


class TestSetupAllMiddleware:

    def test_setup_all_middleware_adds_multiple(self):
        from core.middleware import setup_all_middleware
        app = FastAPI()
        config = {"core": {"server": {"cors_origins": ["http://localhost"]}}}
        setup_all_middleware(app, config)
        assert len(app.user_middleware) >= 3

    def test_setup_all_middleware_with_i18n(self):
        from core.middleware import setup_all_middleware
        app = FastAPI()
        mock_i18n = MagicMock()
        mock_i18n.t = MagicMock(return_value="translated")
        config = {"core": {"server": {"cors_origins": ["http://localhost"]}}}
        setup_all_middleware(app, config, i18n=mock_i18n)
        assert len(app.user_middleware) >= 3
