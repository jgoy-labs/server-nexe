"""
Tests for uncovered lines in plugins/ollama_module/ files.

Covers:
- cli.py: lines 24-26, 37, 250-254, 257-260
- module.py: lines 21-22, 380-386
- health.py: lines 19-20
- workflow/nodes/ollama_node.py: lines 15-16, 332-333
"""

import pytest
import sys
from unittest.mock import patch, MagicMock, AsyncMock


# ═══════════════════════════════════════════════════════════════
# cli.py — uncovered lines
# ═══════════════════════════════════════════════════════════════

class TestOllamaCliGaps:

    def test_run_async_helper(self):
        """Line 43: _run_async helper runs coroutine."""
        from plugins.ollama_module.cli import _run_async
        import asyncio

        async def dummy():
            return 42

        result = _run_async(dummy())
        assert result == 42


# ═══════════════════════════════════════════════════════════════
# module.py — uncovered lines
# ═══════════════════════════════════════════════════════════════

class TestOllamaModuleGaps:

    def test_metadata_property(self):
        """metadata property returns ModuleMetadata."""
        from plugins.ollama_module.module import OllamaModule
        mod = OllamaModule()
        meta = mod.metadata
        assert meta.name == "ollama_module"
        assert meta.version is not None

    def test_get_info(self):
        """get_info returns module info dict."""
        from plugins.ollama_module.module import OllamaModule
        mod = OllamaModule()
        info = mod.get_info()
        assert info["name"] == "ollama_module"
        assert "version" in info
        assert "initialized" in info

    @pytest.mark.asyncio
    async def test_initialize_and_shutdown(self):
        """initialize and shutdown lifecycle."""
        from plugins.ollama_module.module import OllamaModule
        mod = OllamaModule()
        with patch.object(mod.client, 'ensure_ollama_running', new=AsyncMock()), \
             patch.object(mod.client, 'check_connection', new=AsyncMock(return_value=True)):
            result = await mod.initialize({"services": {}})
        assert result is True
        assert mod._initialized is True
        await mod.shutdown()
        assert mod._initialized is False


# ═══════════════════════════════════════════════════════════════
# health.py — uncovered lines
# ═══════════════════════════════════════════════════════════════

class TestOllamaHealthGaps:

    def test_httpx_not_installed(self):
        """Lines 19-20: httpx not available returns DEGRADED."""
        from plugins.ollama_module import health
        original_httpx = health.httpx

        health.httpx = None
        try:
            result = health.get_health()
            assert result["status"] == "DEGRADED"
            assert "httpx not installed" in result["error"]
        finally:
            health.httpx = original_httpx


