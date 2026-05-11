"""Tests for plugins/ollama_module/cli/main.py — coverage gaps."""


class TestOllamaCLIModule:
    def test_app_exists(self):
        from plugins.ollama_module.cli.main import app
        assert app is not None

    def test_run_async_helper(self):
        import asyncio
        from plugins.ollama_module.cli.main import _run_async

        async def _coro():
            return 42

        result = _run_async(_coro())
        assert result == 42

    def test_rich_available(self):
        from plugins.ollama_module.cli.main import RICH_AVAILABLE
        assert isinstance(RICH_AVAILABLE, bool)
