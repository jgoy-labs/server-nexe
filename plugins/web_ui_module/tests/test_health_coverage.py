"""Tests for plugins/web_ui_module/health.py — coverage gaps."""
import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock, patch


class TestGetHealthInEventLoop:
    """get_health() called from inside a running event loop."""

    def test_initialized_returns_healthy(self):
        mock_meta = MagicMock()
        mock_meta.name = "web_ui_module"
        mock_meta.version = "1.0.0"

        mock_module = MagicMock()
        mock_module._initialized = True
        mock_module.metadata = mock_meta

        with patch("plugins.web_ui_module.manifest.get_module_instance", return_value=mock_module):
            from plugins.web_ui_module.health import get_health

            async def _run():
                return get_health()

            result = asyncio.run(_run())

        assert result["status"] == "healthy"
        assert result["module"] == "web_ui_module"
        assert result["initialized"] is True

    def test_not_initialized_returns_unknown(self):
        mock_meta = MagicMock()
        mock_meta.name = "web_ui_module"
        mock_meta.version = "1.0.0"

        mock_module = MagicMock()
        mock_module._initialized = False
        mock_module.metadata = mock_meta

        with patch("plugins.web_ui_module.manifest.get_module_instance", return_value=mock_module):
            from plugins.web_ui_module.health import get_health

            async def _run():
                return get_health()

            result = asyncio.run(_run())

        assert result["status"] == "unknown"
        assert result["initialized"] is False


class TestGetHealthOutsideEventLoop:
    """get_health() called outside an event loop."""

    def test_delegates_to_async_health_check(self):
        mock_health_result = MagicMock()
        mock_health_result.to_dict.return_value = {
            "status": "healthy",
            "module": "web_ui_module",
        }

        mock_module = MagicMock()
        mock_module.health_check = AsyncMock(return_value=mock_health_result)

        with patch("plugins.web_ui_module.manifest.get_module_instance", return_value=mock_module):
            from plugins.web_ui_module.health import get_health
            result = get_health()

        assert result["status"] == "healthy"
        mock_module.health_check.assert_awaited_once()
