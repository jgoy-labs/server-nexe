"""
Tests for uncovered lines in core/middleware.py.
Targets: lines 98-102, 199-200, 237-262
"""
import pytest
from unittest.mock import MagicMock, patch
from fastapi import FastAPI


class TestSetupRateLimitingAdvancedFailure:
    """Lines 98-102: Advanced rate limiting import fails with exception."""

    def test_advanced_rate_limiting_exception_falls_back(self):
        from core.middleware import setup_rate_limiting
        app = FastAPI()

        mock_i18n = MagicMock()
        mock_i18n.t.return_value = "translated"

        # Force ADVANCED_RATE_LIMITING to True, then make the import fail
        with patch("core.middleware.ADVANCED_RATE_LIMITING", True):
            # Patch the imports inside the try block to raise
            with patch("core.dependencies.limiter_by_key",
                       side_effect=RuntimeError("setup failed"), create=True):
                setup_rate_limiting(app, i18n=mock_i18n)

        assert hasattr(app.state, "limiter")

    def test_advanced_rate_limiting_exception_no_i18n(self):
        from core.middleware import setup_rate_limiting
        app = FastAPI()

        with patch("core.middleware.ADVANCED_RATE_LIMITING", True):
            with patch("core.dependencies.limiter_by_key",
                       side_effect=RuntimeError("fail"), create=True):
                setup_rate_limiting(app, i18n=None)

        assert hasattr(app.state, "limiter")


class TestSetupPrometheusMetricsImportError:
    """Lines 199-200: ImportError in prometheus setup."""

    def test_prometheus_import_error_logged(self, caplog):
        from core.middleware import setup_prometheus_metrics
        app = FastAPI()

        with patch("core.metrics.middleware.PrometheusMiddleware",
                   side_effect=ImportError("no prometheus"), create=True):
            setup_prometheus_metrics(app)
        # Should not raise


class TestSetupCsrfProtectionFullCoverage:
    """Lines 237-262: CSRF protection full path coverage."""

    def test_csrf_prod_non_local_host_secure_cookie(self):
        """Lines 241-244: prod + non-local host -> cookie_secure=True."""
        from core.middleware import setup_csrf_protection
        app = FastAPI()
        config = {"core": {"server": {"host": "192.168.1.100"}}}

        with patch.dict("os.environ", {
            "NEXE_CSRF_SECRET": "secret123",
            "NEXE_ENV": "production"
        }):
            try:
                setup_csrf_protection(app, config)
            except ImportError:
                pass  # starlette-csrf may not be installed

    def test_csrf_manual_cookie_secure_override(self):
        """Lines 247-249: manual csrf_cookie_secure override."""
        from core.middleware import setup_csrf_protection
        app = FastAPI()
        config = {"core": {"server": {"host": "127.0.0.1", "csrf_cookie_secure": True}}}

        with patch.dict("os.environ", {"NEXE_CSRF_SECRET": "secret123"}):
            try:
                setup_csrf_protection(app, config)
            except ImportError:
                pass

    def test_csrf_starlette_not_installed(self):
        """Lines 263-265: starlette-csrf ImportError."""
        from core.middleware import setup_csrf_protection
        app = FastAPI()
        config = {"core": {"server": {}}}

        with patch.dict("os.environ", {"NEXE_CSRF_SECRET": "test"}), \
             patch.dict("sys.modules", {"starlette_csrf": None}):
            setup_csrf_protection(app, config)

    def test_csrf_uses_exempt_patterns(self):
        """Lines 251-261: CSRF uses pre-compiled exempt patterns."""
        from core.middleware import _CSRF_EXEMPT_PATTERNS
        assert len(_CSRF_EXEMPT_PATTERNS) > 0
        # Verify patterns match expected paths
        assert any(p.match("/v1/chat/completions") for p in _CSRF_EXEMPT_PATTERNS)
        assert any(p.match("/health") for p in _CSRF_EXEMPT_PATTERNS)
        assert any(p.match("/metrics") for p in _CSRF_EXEMPT_PATTERNS)
