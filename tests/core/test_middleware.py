"""
Tests for core/middleware.py
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
        """i18n returns the key (not found) → fallback"""
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
        # Verify that middleware was added (the middleware list has grown)
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
        # Verify middleware added
        assert len(app.user_middleware) > 0

    def test_default_localhost_config(self):
        from core.middleware import setup_trusted_hosts
        app = FastAPI()
        config = {}  # no configuration → 127.0.0.1 by default
        setup_trusted_hosts(app, config)
        assert len(app.user_middleware) > 0

    def test_zero_host_not_added(self):
        """0.0.0.0 must not be added to allowed_hosts"""
        from core.middleware import setup_trusted_hosts
        from core.config import get_localhost_aliases
        app = FastAPI()
        config = {"core": {"server": {"host": "0.0.0.0"}}}
        setup_trusted_hosts(app, config)
        # The middleware is added, but 0.0.0.0 must NOT be in allowed_hosts
        # (security regression guard: binding to 0.0.0.0 must not whitelist it).
        assert len(app.user_middleware) > 0
        mw = app.user_middleware[0]
        allowed = mw.kwargs["allowed_hosts"]
        assert "0.0.0.0" not in allowed
        # localhost aliases are always present regardless of the bind host
        for alias in get_localhost_aliases():
            assert alias in allowed


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
        config = {}  # no configuration → default value
        setup_request_size_limit(app, config)
        assert len(app.user_middleware) > 0


class TestSetupRateLimiting:
    def test_basic_rate_limiting(self):
        from core.middleware import setup_rate_limiting
        app = FastAPI()
        # ADVANCED_RATE_LIMITING=False by default in most test environments
        with patch("core.middleware.ADVANCED_RATE_LIMITING", False):
            setup_rate_limiting(app)
        assert hasattr(app.state, "limiter")

    def test_basic_rate_limiting_sets_state(self):
        from core.middleware import setup_rate_limiting
        app = FastAPI()
        with patch("core.middleware.ADVANCED_RATE_LIMITING", False):
            setup_rate_limiting(app)
        assert app.state.limiter is not None

    def test_advanced_mode_does_not_publish_orphan_limiters(self):
        """MC-123: with ADVANCED_RATE_LIMITING on, only the per-IP limiter is
        published. The advanced limiters (by_key / composite / by_endpoint) were
        set on app.state but consumed by nobody — dead wiring — so they must NOT
        be published any more.

        Mutation guard: re-add ``app.state.limiter_by_key = limiter_by_key`` (or a
        sibling) to setup_rate_limiting and this test goes RED. (The previous test
        here was theatre: it patched names the code no longer references and only
        asserted ``hasattr(app.state, "limiter")``, so restoring the orphan wiring
        would not fail it.)
        """
        from core.middleware import setup_rate_limiting
        app = FastAPI()
        with patch("core.middleware.ADVANCED_RATE_LIMITING", True):
            setup_rate_limiting(app)
        # the real, enforced per-IP limiter is always present
        assert hasattr(app.state, "limiter")
        for orphan in ("limiter_by_key", "limiter_composite", "limiter_by_endpoint"):
            assert not hasattr(app.state, orphan), (
                f"{orphan} is dead wiring (no consumer) and must not be published (MC-123)"
            )

    def test_advanced_mode_does_not_wire_noop_cleanup_task(self):
        """MC-124: the hourly rate-limit cleanup task iterated an always-empty
        tracker (RateLimitTracker.record_request has no production caller), so it
        must no longer be wired onto app.state.

        Mutation guard: re-add ``app.state.start_rate_limit_cleanup = ...`` to
        setup_rate_limiting and this test goes RED.
        """
        from core.middleware import setup_rate_limiting
        app = FastAPI()
        with patch("core.middleware.ADVANCED_RATE_LIMITING", True):
            setup_rate_limiting(app)
        assert not hasattr(app.state, "start_rate_limit_cleanup"), (
            "the no-op rate-limit cleanup task must not be wired (MC-124)"
        )


class TestSetupCsrfProtection:
    def test_csrf_import_error(self):
        """starlette-csrf is mandatory — missing module raises ImportError."""
        from core.middleware import setup_csrf_protection
        app = FastAPI()
        config = {"core": {"server": {}}}
        with patch.dict('os.environ', {'NEXE_CSRF_SECRET': 'test'}, clear=False), \
             patch.dict('sys.modules', {'starlette_csrf': None}):
            with pytest.raises((ImportError, ModuleNotFoundError)):
                setup_csrf_protection(app, config)


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
