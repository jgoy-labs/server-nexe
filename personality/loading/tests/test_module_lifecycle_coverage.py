"""Tests for personality/loading/module_lifecycle.py — coverage gaps."""
from unittest.mock import MagicMock


class TestModuleLifecycle:
    def test_module_imports(self):
        from personality.loading import module_lifecycle
        assert module_lifecycle is not None
