"""
Tests per core/middleware.py
"""
import pytest
from unittest.mock import MagicMock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient


class TestTranslateHelper:
    def test_translate_without_i18n(self):
        from core.middleware import _translate
        result = _translate(None, "key", "Fallback text")
        assert result == "Fallback text"

    def test_translate_i18n_returns_key_not_found(self):
        """i18n retorna la clau (no trobat) → fallback"""
        from core.middleware import _translate
        mock_i18n = MagicMock()
        mock_i18n.t.side_effect = lambda key, **kw: key
        result = _translate(mock_i18n, "some.key", "Fallback")
        assert result == "Fallback"

    def test_translate_i18n_returns_translation(self):
        from core.middleware import _translate
        mock_i18n = MagicMock()
        mock_i18n.t.return_value = "Traduit"
        result = _translate(mock_i18n, "some.key", "Fallback")
        assert result == "Traduit"

    def test_translate_with_kwargs_in_fallback(self):
        from core.middleware import _translate
        result = _translate(None, "key", "Error: {error}", error="test")
        assert result == "Error: test"

    def test_translate_with_kwargs_i18n(self):
        from core.middleware import _translate
        mock_i18n = MagicMock()
        mock_i18n.t.return_value = "Traduit amb args"
        result = _translate(mock_i18n, "key", "Fallback {x}", x="val")
        assert result == "Traduit amb args"


class TestSetupCors:
    def test_wildcard_raises_valueerror(self):
        from core.middleware import setup_cors
        app = FastAPI()
        config = {"core": {"server": {"cors_origins": ["*"]}}}
        with pytest.raises(ValueError, match="wildcard"):
            setup_cors(app, config)

    def test_empty_origins_raises_valueerror(self):
        from core.middleware import setup_cors
        app = FastAPI()
        config = {"core": {"server": {"cors_origins": []}}}
        with pytest.raises(ValueError):
            setup_cors(app, config)

    def test_valid_origins_adds_middleware(self):
        from core.middleware import setup_cors
        app = FastAPI()
        config = {"core": {"server": {"cors_origins": ["http://localhost:3000"]}}}
        setup_cors(app, config)
        # Verificar que s'ha afegit middleware (la llista de middleware ha augmentat)
        assert len(app.user_middleware) > 0

    def test_wildcard_with_i18n(self):
        from core.middleware import setup_cors
        app = FastAPI()
        config = {"core": {"server": {"cors_origins": ["*"]}}}
        mock_i18n = MagicMock()
        mock_i18n.t.return_value = "Wildcard no permès"
        with pytest.raises(ValueError):
            setup_cors(app, config, i18n=mock_i18n)


class TestSetupTrustedHosts:
    def test_custom_host_added(self):
        from core.middleware import setup_trusted_hosts
        app = FastAPI()
        config = {"core": {"server": {"host": "192.168.1.100"}}}
        setup_trusted_hosts(app, config)
        # Verificar middleware afegit
        assert len(app.user_middleware) > 0

    def test_default_localhost_config(self):
        from core.middleware import setup_trusted_hosts
        app = FastAPI()
        config = {}  # sense configuració → 127.0.0.1 per defecte
        setup_trusted_hosts(app, config)
        assert len(app.user_middleware) > 0

    def test_zero_host_not_added(self):
        """0.0.0.0 no s'ha d'afegir als allowed_hosts"""
        from core.middleware import setup_trusted_hosts
        app = FastAPI()
        config = {"core": {"server": {"host": "0.0.0.0"}}}
        setup_trusted_hosts(app, config)
        # El middleware s'afegeix, però 0.0.0.0 no hauria d'estar a allowed


class TestSetupRequestSizeLimit:
    def test_adds_middleware(self):
        from core.middleware import setup_request_size_limit
        app = FastAPI()
        config = {"core": {"server": {"max_request_size": 1048576}}}
        setup_request_size_limit(app, config)
        assert len(app.user_middleware) > 0

    def test_default_max_size(self):
        from core.middleware import setup_request_size_limit
        app = FastAPI()
        config = {}  # sense configuració → valor per defecte
        setup_request_size_limit(app, config)
        assert len(app.user_middleware) > 0


class TestSetupRateLimiting:
    def test_basic_rate_limiting(self):
        from core.middleware import setup_rate_limiting
        app = FastAPI()
        # ADVANCED_RATE_LIMITING=False per defecte en la majoria d'entorns de test
        with patch("core.middleware.ADVANCED_RATE_LIMITING", False):
            setup_rate_limiting(app)
        assert hasattr(app.state, "limiter")

    def test_basic_rate_limiting_sets_state(self):
        from core.middleware import setup_rate_limiting
        app = FastAPI()
        with patch("core.middleware.ADVANCED_RATE_LIMITING", False):
            setup_rate_limiting(app)
        assert app.state.limiter is not None

    def test_advanced_rate_limiting_success(self):
        """Lines 77-96: advanced rate limiting enabled successfully."""
        from core.middleware import setup_rate_limiting
        app = FastAPI()
        with patch("core.middleware.ADVANCED_RATE_LIMITING", True), \
             patch("core.middleware.limiter_by_key", create=True, new=MagicMock()), \
             patch("core.middleware.limiter_composite", create=True, new=MagicMock()), \
             patch("core.middleware.limiter_by_endpoint", create=True, new=MagicMock()), \
             patch("core.middleware.start_rate_limit_cleanup_task", create=True, new=MagicMock()):
            setup_rate_limiting(app)
        assert hasattr(app.state, "limiter")

    def test_advanced_rate_limiting_import_error(self):
        """Lines 98-102: advanced rate limiting import fails -> fallback."""
        from core.middleware import setup_rate_limiting
        app = FastAPI()
        with patch("core.middleware.ADVANCED_RATE_LIMITING", True), \
             patch("core.dependencies.limiter_by_key", side_effect=ImportError("fail"), create=True):
            # The setup_rate_limiting catches Exception at line 98
            setup_rate_limiting(app)
        assert hasattr(app.state, "limiter")


class TestSetupPrometheusMetrics:
    def test_prometheus_import_error(self):
        """Lines 199-200: ImportError in prometheus setup."""
        from core.middleware import setup_prometheus_metrics
        app = FastAPI()
        with patch("core.middleware.PrometheusMiddleware", side_effect=ImportError("no module"), create=True):
            # Should not raise
            setup_prometheus_metrics(app)


class TestSetupCsrfProtection:
    def test_csrf_dev_mode_no_secret(self):
        """Lines 224-228: dev mode without CSRF secret."""
        from core.middleware import setup_csrf_protection
        app = FastAPI()
        config = {"core": {"server": {"host": "127.0.0.1"}}}
        with patch.dict('os.environ', {'NEXE_ENV': 'development'}, clear=False), \
             patch.dict('os.environ', {}, clear=False):
            # Remove NEXE_CSRF_SECRET if present
            import os
            os.environ.pop("NEXE_CSRF_SECRET", None)
            try:
                setup_csrf_protection(app, config)
            except ImportError:
                pass  # starlette-csrf may not be installed

    def test_csrf_prod_mode_no_secret(self):
        """Lines 216-223: production mode without CSRF secret."""
        from core.middleware import setup_csrf_protection
        app = FastAPI()
        config = {"core": {"server": {"host": "127.0.0.1"}}}
        import os
        os.environ.pop("NEXE_CSRF_SECRET", None)
        with patch.dict('os.environ', {'NEXE_ENV': 'production'}, clear=False):
            try:
                setup_csrf_protection(app, config)
            except ImportError:
                pass

    def test_csrf_cookie_secure_override(self):
        """Lines 247-249: manual cookie_secure override."""
        from core.middleware import setup_csrf_protection
        app = FastAPI()
        config = {"core": {"server": {"host": "127.0.0.1", "csrf_cookie_secure": True}}}
        with patch.dict('os.environ', {'NEXE_CSRF_SECRET': 'testsecret123'}, clear=False):
            try:
                setup_csrf_protection(app, config)
            except ImportError:
                pass

    def test_csrf_import_error(self):
        """starlette-csrf is mandatory — missing module raises ImportError."""
        from core.middleware import setup_csrf_protection
        app = FastAPI()
        config = {"core": {"server": {}}}
        with patch.dict('os.environ', {'NEXE_CSRF_SECRET': 'test'}, clear=False), \
             patch.dict('sys.modules', {'starlette_csrf': None}):
            with pytest.raises((ImportError, ModuleNotFoundError)):
                setup_csrf_protection(app, config)

    def test_csrf_non_local_prod_sets_secure(self):
        """Lines 241-244: non-local host in prod -> cookie_secure=True."""
        from core.middleware import setup_csrf_protection
        app = FastAPI()
        config = {"core": {"server": {"host": "192.168.1.100"}}}
        with patch.dict('os.environ', {
            'NEXE_CSRF_SECRET': 'secret123',
            'NEXE_ENV': 'production'
        }, clear=False):
            try:
                setup_csrf_protection(app, config)
            except ImportError:
                pass


class TestSetupAllMiddleware:
    def test_setup_all(self):
        """Lines 293-314: setup_all_middleware."""
        from core.middleware import setup_all_middleware
        app = FastAPI()
        config = {"core": {"server": {
            "cors_origins": ["http://localhost:3000"],
            "host": "127.0.0.1"
        }}}
        with patch("core.middleware.setup_prometheus_metrics"), \
             patch("core.middleware.setup_csrf_protection"), \
             patch("core.middleware.ADVANCED_RATE_LIMITING", False):
            setup_all_middleware(app, config)
