"""
Tests for uncovered lines in core/container.py.
Targets: lines 57-58, 66-67, 75-76 (deprecation warnings when NOT in tests)
"""
import pytest
import warnings
from unittest.mock import patch


class TestContainerDeprecationWarnings:
    """Lines 57-58, 66-67, 75-76: deprecation warnings in non-test context."""

    def setup_method(self):
        from core.container import Container
        Container.clear()

    def test_register_warns_when_not_in_tests(self):
        """Lines 57-58: register() warns outside of test context."""
        from core.container import Container

        with patch("core.container._IN_TESTS", False):
            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                Container.register("test_svc", "value")
                assert any(issubclass(x.category, DeprecationWarning) for x in w)

    def test_register_factory_warns_when_not_in_tests(self):
        """Lines 66-67: register_factory() warns outside of test context."""
        from core.container import Container

        with patch("core.container._IN_TESTS", False):
            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                Container.register_factory("test_fac", lambda: "val")
                assert any(issubclass(x.category, DeprecationWarning) for x in w)

    def test_get_warns_when_not_in_tests(self):
        """Lines 75-76: get() warns outside of test context."""
        from core.container import Container
        Container.register("svc", "val")

        with patch("core.container._IN_TESTS", False):
            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                result = Container.get("svc")
                assert result == "val"
                assert any(issubclass(x.category, DeprecationWarning) for x in w)
