"""
Tests for core/dependencies.py
Covers uncovered lines: 26-33
"""
import pytest
from unittest.mock import patch, MagicMock


class TestDependenciesImportFallback:
    """Tests for import fallback (lines 26-33)"""

    def test_advanced_rate_limiting_available(self):
        """Lines 17-25: advanced rate limiting successfully imported"""
        from core.dependencies import ADVANCED_RATE_LIMITING, limiter
        # Just verify the module loads and exposes the right symbols
        assert isinstance(ADVANCED_RATE_LIMITING, bool)
        assert limiter is not None

    def test_fallback_when_security_not_available(self):
        """Lines 26-33: ImportError fallback creates basic limiter"""
        import importlib
        import sys

        # Force reimport with security module unavailable
        # Save and remove the module
        mod_key = 'core.dependencies'
        if mod_key in sys.modules:
            saved = sys.modules.pop(mod_key)
        else:
            saved = None

        # Also remove security module to force ImportError
        security_keys = [k for k in sys.modules if k.startswith('plugins.security')]
        saved_security = {k: sys.modules.pop(k) for k in security_keys}

        try:
            with patch.dict('sys.modules', {'plugins.security.core.rate_limiting': None}):
                # Force the ImportError path
                import core.dependencies as deps
                importlib.reload(deps)

                assert deps.ADVANCED_RATE_LIMITING is False
                assert deps.limiter is not None
                assert deps.limiter_by_key is None
                assert deps.limiter_composite is None
                assert deps.limiter_by_endpoint is None
                assert deps.rate_limit_tracker is None
                assert deps.start_rate_limit_cleanup_task is None
        finally:
            # Restore
            if saved is not None:
                sys.modules[mod_key] = saved
            for k, v in saved_security.items():
                sys.modules[k] = v
            # Reload to restore original state
            importlib.reload(sys.modules.get(mod_key, saved))

    def test_all_exports_present(self):
        """Check __all__ exports"""
        from core.dependencies import __all__
        expected = [
            'limiter', 'limiter_global', 'limiter_by_key',
            'limiter_composite', 'limiter_by_endpoint',
            'rate_limit_tracker', 'start_rate_limit_cleanup_task',
            'ADVANCED_RATE_LIMITING',
        ]
        for name in expected:
            assert name in __all__
