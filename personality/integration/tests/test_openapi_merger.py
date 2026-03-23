"""
Tests per personality/integration/openapi_merger.py
Covers uncovered lines: 69-74, 78-88, 108-113, 117-126.
"""

import pytest
from unittest.mock import patch, MagicMock
from fastapi import FastAPI

from personality.integration.openapi_merger import OpenAPIMerger


@pytest.fixture
def merger():
    app = FastAPI()
    return OpenAPIMerger(main_app=app)


@pytest.fixture
def merger_with_i18n():
    app = FastAPI()
    i18n = MagicMock()
    return OpenAPIMerger(main_app=app, i18n_manager=i18n)


class TestMergeModuleOpenapi:
    def test_merge_success(self, merger):
        """Lines 59-76: successful merge."""
        result = merger.merge_module_openapi(
            "test_module", {"endpoint1": {}, "endpoint2": {}}, "/api/test"
        )
        assert result is True
        assert "test_module" in merger._module_specs

    def test_merge_with_logger_available(self, merger_with_i18n):
        """Lines 68-74: merge with logger (LOGGER_AVAILABLE guard removed)."""
        result = merger_with_i18n.merge_module_openapi(
            "mod1", {"ep": {}}, "/api/mod1"
        )
        assert result is True

    def test_merge_exception_returns_false(self, merger):
        """Lines 78-88: exception during merge returns False."""
        with patch.object(merger, '_extract_module_openapi',
                          side_effect=RuntimeError("fail")):
            result = merger.merge_module_openapi("bad_mod", {}, "/api/bad")
        assert result is False

    def test_merge_exception_with_logger(self, merger_with_i18n):
        """Lines 79-86: exception with logger (LOGGER_AVAILABLE guard removed)."""
        with patch("personality.integration.openapi_merger.logger") as mock_logger, \
             patch.object(merger_with_i18n, '_extract_module_openapi',
                          side_effect=RuntimeError("fail")):
            result = merger_with_i18n.merge_module_openapi("bad_mod", {}, "/api/bad")
        assert result is False
        mock_logger.error.assert_called_once()

    def test_merge_none_spec_returns_false(self, merger):
        """Line 63: _extract_module_openapi returns None."""
        with patch.object(merger, '_extract_module_openapi', return_value=None):
            result = merger.merge_module_openapi("mod", {}, "/api/mod")
        assert result is False


class TestRemoveModuleOpenapi:
    def test_remove_existing(self, merger):
        """Lines 100-115: remove existing module."""
        merger._module_specs["test_mod"] = {"prefix": "/api/test"}
        result = merger.remove_module_openapi("test_mod")
        assert result is True
        assert "test_mod" not in merger._module_specs

    def test_remove_nonexistent(self, merger):
        """Line 102: module not found, still returns True."""
        result = merger.remove_module_openapi("nonexistent")
        assert result is True

    def test_remove_with_logger(self, merger_with_i18n):
        """Lines 107-113: remove with logger (LOGGER_AVAILABLE guard removed)."""
        merger_with_i18n._module_specs["mod1"] = {"prefix": "/api"}
        result = merger_with_i18n.remove_module_openapi("mod1")
        assert result is True

    def test_remove_exception_returns_false(self, merger):
        """Lines 117-126: exception during remove returns False."""
        with patch.object(merger, '_regenerate_unified_openapi',
                          side_effect=RuntimeError("fail")):
            merger._module_specs["mod"] = {"prefix": "/api"}
            result = merger.remove_module_openapi("mod")
        assert result is False

    def test_remove_exception_with_logger(self, merger_with_i18n):
        """Lines 118-125: exception with logger (LOGGER_AVAILABLE guard removed)."""
        merger_with_i18n._module_specs["mod"] = {"prefix": "/api"}
        with patch("personality.integration.openapi_merger.logger") as mock_logger, \
             patch.object(merger_with_i18n, '_regenerate_unified_openapi',
                          side_effect=RuntimeError("fail")):
            result = merger_with_i18n.remove_module_openapi("mod")
        assert result is False
        mock_logger.error.assert_called_once()


class TestGetUnifiedSpec:
    def test_empty_spec(self, merger):
        spec = merger.get_unified_spec()
        assert spec["modules"] == []
        assert spec["total_modules"] == 0

    def test_spec_with_modules(self, merger):
        merger._module_specs["mod1"] = {"prefix": "/api/mod1"}
        merger._module_specs["mod2"] = {"prefix": "/api/mod2"}
        spec = merger.get_unified_spec()
        assert len(spec["modules"]) == 2
        assert spec["total_modules"] == 2
