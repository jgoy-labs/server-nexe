"""
Tests for uncovered lines in core/middleware.py.
Targets: lines 98-102, 199-200, 237-262
"""
import pytest
from unittest.mock import MagicMock, patch
from fastapi import FastAPI


class TestSetupCsrfProtectionFullCoverage:
    """Lines 237-262: CSRF protection full path coverage."""

    def test_csrf_starlette_not_installed(self):
        """starlette-csrf is mandatory — missing module raises ImportError."""
        from core.middleware import setup_csrf_protection
        app = FastAPI()
        config = {"core": {"server": {}}}

        with patch.dict("os.environ", {"NEXE_CSRF_SECRET": "test"}), \
             patch.dict("sys.modules", {"starlette_csrf": None}):
            with pytest.raises((ImportError, ModuleNotFoundError)):
                setup_csrf_protection(app, config)

    def test_csrf_uses_exempt_patterns(self):
        """Lines 251-261: CSRF uses pre-compiled exempt patterns."""
        from core.middleware import _CSRF_EXEMPT_PATTERNS
        assert len(_CSRF_EXEMPT_PATTERNS) > 0
        # Verify patterns match expected paths
        assert any(p.match("/v1/chat/completions") for p in _CSRF_EXEMPT_PATTERNS)
        assert any(p.match("/health") for p in _CSRF_EXEMPT_PATTERNS)
        assert any(p.match("/metrics") for p in _CSRF_EXEMPT_PATTERNS)
