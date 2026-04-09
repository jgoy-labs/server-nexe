"""
Tests for memory/memory/cli.py - Memory CLI module.
The cli.py file coexists with a cli/ package directory.
Python resolves the package directory first, so we use importlib
to load cli.py directly, injecting its dependencies first.
"""

import pytest
import asyncio
import argparse
import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock


def _load_cli_module():
    """Load memory/memory/cli.py directly since the cli/ package shadows it."""
    cli_path = Path(__file__).parent.parent / "cli.py"

    # Create a fake parent package context so relative imports work
    # The cli.py does: from .module import MemoryModule
    # from .models.memory_entry import MemoryEntry
    # from .models.memory_types import MemoryType
    # These resolve relative to memory.memory

    # Ensure memory.memory is importable
    import memory.memory

    spec = importlib.util.spec_from_file_location(
        "memory.memory._cli_file",
        cli_path,
        submodule_search_locations=[]
    )
    mod = importlib.util.module_from_spec(spec)
    # Set the package so relative imports resolve to memory.memory
    mod.__package__ = "memory.memory"
    sys.modules["memory.memory._cli_file"] = mod
    spec.loader.exec_module(mod)
    return mod


# Load the module once
_cli_mod = _load_cli_module()
MemoryCLI = _cli_mod.MemoryCLI
create_parser = _cli_mod.create_parser
async_main_func = _cli_mod.async_main
main_func = _cli_mod.main


class TestMemoryCLI:
    """Tests for MemoryCLI class."""

    def test_init(self):
        """Test MemoryCLI initializes with no module."""
        cli = MemoryCLI()
        assert cli.module is None

    @pytest.mark.asyncio
    async def test_initialize_success(self):
        """Test successful initialization."""
        cli = MemoryCLI()
        mock_module = MagicMock()
        mock_module.initialize = AsyncMock(return_value=True)

        with patch.object(_cli_mod, "MemoryModule") as MockModule:
            MockModule.get_instance.return_value = mock_module
            result = await cli.initialize()
            assert result is True
            assert cli.module is mock_module

    @pytest.mark.asyncio
    async def test_initialize_failure(self):
        """Test initialization failure."""
        cli = MemoryCLI()
        mock_module = MagicMock()
        mock_module.initialize = AsyncMock(return_value=False)

        with patch.object(_cli_mod, "MemoryModule") as MockModule:
            MockModule.get_instance.return_value = mock_module
            result = await cli.initialize()
            assert result is False

    @pytest.mark.asyncio
    async def test_initialize_exception(self):
        """Test initialization with exception."""
        cli = MemoryCLI()

        with patch.object(_cli_mod, "MemoryModule") as MockModule:
            MockModule.get_instance.side_effect = RuntimeError("fail")
            result = await cli.initialize()
            assert result is False

    @pytest.mark.asyncio
    async def test_shutdown_with_module(self):
        """Test shutdown when module is set."""
        cli = MemoryCLI()
        cli.module = MagicMock()
        cli.module.shutdown = AsyncMock()
        await cli.shutdown()
        cli.module.shutdown.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_shutdown_without_module(self):
        """Test shutdown when no module."""
        cli = MemoryCLI()
        await cli.shutdown()  # Should not raise

    @pytest.mark.asyncio
    async def test_cmd_store_success(self):
        """Test successful store command."""
        cli = MemoryCLI()
        cli.module = MagicMock()
        cli.module._pipeline = MagicMock()
        cli.module._pipeline.ingest = AsyncMock(return_value=True)

        args = argparse.Namespace(
            content="test content here",
            type="episodic",
            source="cli",
            ttl=1800
        )
        result = await cli.cmd_store(args)
        assert result == 0

    @pytest.mark.asyncio
    async def test_cmd_store_invalid_type(self):
        """Test store with invalid entry type."""
        cli = MemoryCLI()
        cli.module = MagicMock()

        args = argparse.Namespace(
            content="test",
            type="invalid_type",
            source="cli",
            ttl=1800
        )
        result = await cli.cmd_store(args)
        assert result == 1

    @pytest.mark.asyncio
    async def test_cmd_store_no_pipeline(self):
        """Test store when pipeline not initialized."""
        cli = MemoryCLI()
        cli.module = MagicMock()
        cli.module._pipeline = None

        args = argparse.Namespace(
            content="test",
            type="episodic",
            source="cli",
            ttl=1800
        )
        result = await cli.cmd_store(args)
        assert result == 1

    @pytest.mark.asyncio
    async def test_cmd_store_ingest_fails(self):
        """Test store when ingest returns False (duplicate)."""
        cli = MemoryCLI()
        cli.module = MagicMock()
        cli.module._pipeline = MagicMock()
        cli.module._pipeline.ingest = AsyncMock(return_value=False)

        args = argparse.Namespace(
            content="test",
            type="episodic",
            source="cli",
            ttl=1800
        )
        result = await cli.cmd_store(args)
        assert result == 1

    @pytest.mark.asyncio
    async def test_cmd_store_exception(self):
        """Test store with unexpected exception."""
        cli = MemoryCLI()
        cli.module = MagicMock()
        cli.module._pipeline = MagicMock()
        cli.module._pipeline.ingest = AsyncMock(side_effect=RuntimeError("boom"))

        args = argparse.Namespace(
            content="test",
            type="episodic",
            source="cli",
            ttl=1800
        )
        result = await cli.cmd_store(args)
        assert result == 1

    @pytest.mark.asyncio
    async def test_cmd_recall_no_ram_context(self):
        """Test recall with no RAM context."""
        cli = MemoryCLI()
        cli.module = MagicMock()
        cli.module._ram_context = None

        args = argparse.Namespace(limit=20, type=None, safe_mode=True)
        result = await cli.cmd_recall(args)
        assert result == 1

    @pytest.mark.asyncio
    async def test_cmd_recall_with_type(self):
        """Test recall filtered by type."""
        cli = MemoryCLI()
        cli.module = MagicMock()

        mock_entry = MagicMock()
        mock_entry.content = "short content"
        mock_entry.source = "cli"
        mock_entry.id = "abc123"

        cli.module._ram_context = MagicMock()
        cli.module._ram_context.get_recent_by_type = AsyncMock(return_value=[mock_entry])

        args = argparse.Namespace(limit=10, type="episodic", safe_mode=False)
        result = await cli.cmd_recall(args)
        assert result == 0

    @pytest.mark.asyncio
    async def test_cmd_recall_with_type_safe_mode_truncates(self):
        """Test recall with safe_mode truncates long content."""
        cli = MemoryCLI()
        cli.module = MagicMock()

        mock_entry = MagicMock()
        mock_entry.content = "x" * 300
        mock_entry.source = "cli"
        mock_entry.id = "abc123"

        cli.module._ram_context = MagicMock()
        cli.module._ram_context.get_recent_by_type = AsyncMock(return_value=[mock_entry])

        args = argparse.Namespace(limit=10, type="episodic", safe_mode=True)
        result = await cli.cmd_recall(args)
        assert result == 0

    @pytest.mark.asyncio
    async def test_cmd_recall_invalid_type(self):
        """Test recall with invalid type."""
        cli = MemoryCLI()
        cli.module = MagicMock()
        cli.module._ram_context = MagicMock()

        args = argparse.Namespace(limit=10, type="invalid", safe_mode=True)
        result = await cli.cmd_recall(args)
        assert result == 1

    @pytest.mark.asyncio
    async def test_cmd_recall_without_type(self):
        """Test recall without type filter (context string)."""
        cli = MemoryCLI()
        cli.module = MagicMock()
        cli.module._ram_context = MagicMock()
        cli.module._ram_context.to_context_string = AsyncMock(return_value="context text")

        args = argparse.Namespace(limit=20, type=None, safe_mode=True)
        result = await cli.cmd_recall(args)
        assert result == 0

    @pytest.mark.asyncio
    async def test_cmd_recall_exception(self):
        """Test recall with unexpected exception."""
        cli = MemoryCLI()
        cli.module = MagicMock()
        cli.module._ram_context = MagicMock()
        cli.module._ram_context.to_context_string = AsyncMock(side_effect=RuntimeError("fail"))

        args = argparse.Namespace(limit=20, type=None, safe_mode=True)
        result = await cli.cmd_recall(args)
        assert result == 1

    @pytest.mark.asyncio
    async def test_cmd_stats_success(self):
        """Test stats command."""
        cli = MemoryCLI()
        cli.module = MagicMock()
        cli.module._ram_context = MagicMock()
        cli.module._ram_context.get_stats = AsyncMock(return_value={
            'total_available': 5,
            'max_entries': 100,
            'episodic_count': 3,
            'semantic_count': 2,
        })

        args = argparse.Namespace()
        result = await cli.cmd_stats(args)
        assert result == 0

    @pytest.mark.asyncio
    async def test_cmd_stats_no_ram_context(self):
        """Test stats when RAM context is None (legacy fallback path)."""
        cli = MemoryCLI()
        cli.module = MagicMock()
        cli.module._ram_context = None

        # get_memory_service() pot retornar un svc vàlid si un test anterior
        # ha inicialitzat el MemoryService (singleton). Forcem el fallback legacy.
        with patch("memory.memory.module.get_memory_service", return_value=None):
            args = argparse.Namespace()
            result = await cli.cmd_stats(args)
        assert result == 1

    @pytest.mark.asyncio
    async def test_cmd_stats_exception(self):
        """Test stats with exception (legacy fallback path)."""
        cli = MemoryCLI()
        cli.module = MagicMock()
        cli.module._ram_context = MagicMock()
        cli.module._ram_context.get_stats = AsyncMock(side_effect=RuntimeError("fail"))

        # Forcem el fallback legacy per assegurar que l'excepció de get_stats s'exercita.
        with patch("memory.memory.module.get_memory_service", return_value=None):
            args = argparse.Namespace()
            result = await cli.cmd_stats(args)
        assert result == 1

    @pytest.mark.asyncio
    async def test_cmd_cleanup_success(self):
        """Test cleanup command."""
        cli = MemoryCLI()
        cli.module = MagicMock()
        cli.module._flash_memory = MagicMock()
        cli.module._flash_memory.cleanup_expired = AsyncMock(return_value=3)

        args = argparse.Namespace()
        result = await cli.cmd_cleanup(args)
        assert result == 0

    @pytest.mark.asyncio
    async def test_cmd_cleanup_no_flash_memory(self):
        """Test cleanup when FlashMemory is None."""
        cli = MemoryCLI()
        cli.module = MagicMock()
        cli.module._flash_memory = None

        args = argparse.Namespace()
        result = await cli.cmd_cleanup(args)
        assert result == 1

    @pytest.mark.asyncio
    async def test_cmd_cleanup_exception(self):
        """Test cleanup with exception."""
        cli = MemoryCLI()
        cli.module = MagicMock()
        cli.module._flash_memory = MagicMock()
        cli.module._flash_memory.cleanup_expired = AsyncMock(side_effect=RuntimeError("fail"))

        args = argparse.Namespace()
        result = await cli.cmd_cleanup(args)
        assert result == 1


class TestCreateParser:
    """Tests for create_parser function."""

    def test_parser_created(self):
        """Test parser creation."""
        parser = create_parser()
        assert isinstance(parser, argparse.ArgumentParser)

    def test_store_subcommand(self):
        """Test store subcommand parsing."""
        parser = create_parser()
        args = parser.parse_args(["store", "my content", "-t", "episodic", "-s", "test"])
        assert args.command == "store"
        assert args.content == "my content"
        assert args.type == "episodic"
        assert args.source == "test"

    def test_store_defaults(self):
        """Test store default values."""
        parser = create_parser()
        args = parser.parse_args(["store", "content"])
        assert args.type == "episodic"
        assert args.source == "cli"
        assert args.ttl == 1800

    def test_recall_subcommand(self):
        """Test recall subcommand parsing."""
        parser = create_parser()
        args = parser.parse_args(["recall", "-l", "5", "-t", "semantic"])
        assert args.command == "recall"
        assert args.limit == 5
        assert args.type == "semantic"

    def test_recall_defaults(self):
        """Test recall default values."""
        parser = create_parser()
        args = parser.parse_args(["recall"])
        assert args.limit == 20
        assert args.type is None
        assert args.safe_mode is True

    def test_stats_subcommand(self):
        """Test stats subcommand."""
        parser = create_parser()
        args = parser.parse_args(["stats"])
        assert args.command == "stats"

    def test_cleanup_subcommand(self):
        """Test cleanup subcommand."""
        parser = create_parser()
        args = parser.parse_args(["cleanup"])
        assert args.command == "cleanup"

    def test_no_command(self):
        """Test parsing with no command."""
        parser = create_parser()
        args = parser.parse_args([])
        assert args.command is None


class TestAsyncMain:
    """Tests for async_main function."""

    @pytest.mark.asyncio
    async def test_async_main_init_fails(self):
        """Test async_main when init fails."""
        args = argparse.Namespace(command="store")

        with patch.object(_cli_mod, "MemoryCLI") as MockCLI:
            instance = MockCLI.return_value
            instance.initialize = AsyncMock(return_value=False)
            instance.shutdown = AsyncMock()
            result = await async_main_func(args)
            assert result == 1

    @pytest.mark.asyncio
    async def test_async_main_store(self):
        """Test async_main with store command."""
        args = argparse.Namespace(command="store")

        with patch.object(_cli_mod, "MemoryCLI") as MockCLI:
            instance = MockCLI.return_value
            instance.initialize = AsyncMock(return_value=True)
            instance.cmd_store = AsyncMock(return_value=0)
            instance.shutdown = AsyncMock()
            result = await async_main_func(args)
            assert result == 0
            instance.shutdown.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_async_main_recall(self):
        """Test async_main with recall command."""
        args = argparse.Namespace(command="recall")

        with patch.object(_cli_mod, "MemoryCLI") as MockCLI:
            instance = MockCLI.return_value
            instance.initialize = AsyncMock(return_value=True)
            instance.cmd_recall = AsyncMock(return_value=0)
            instance.shutdown = AsyncMock()
            result = await async_main_func(args)
            assert result == 0

    @pytest.mark.asyncio
    async def test_async_main_stats(self):
        """Test async_main with stats command."""
        args = argparse.Namespace(command="stats")

        with patch.object(_cli_mod, "MemoryCLI") as MockCLI:
            instance = MockCLI.return_value
            instance.initialize = AsyncMock(return_value=True)
            instance.cmd_stats = AsyncMock(return_value=0)
            instance.shutdown = AsyncMock()
            result = await async_main_func(args)
            assert result == 0

    @pytest.mark.asyncio
    async def test_async_main_cleanup(self):
        """Test async_main with cleanup command."""
        args = argparse.Namespace(command="cleanup")

        with patch.object(_cli_mod, "MemoryCLI") as MockCLI:
            instance = MockCLI.return_value
            instance.initialize = AsyncMock(return_value=True)
            instance.cmd_cleanup = AsyncMock(return_value=0)
            instance.shutdown = AsyncMock()
            result = await async_main_func(args)
            assert result == 0

    @pytest.mark.asyncio
    async def test_async_main_no_command(self):
        """Test async_main with no command."""
        args = argparse.Namespace(command=None)

        with patch.object(_cli_mod, "MemoryCLI") as MockCLI:
            instance = MockCLI.return_value
            instance.initialize = AsyncMock(return_value=True)
            instance.shutdown = AsyncMock()
            result = await async_main_func(args)
            assert result == 1


class TestMain:
    """Tests for the main() entry point."""

    def test_main_keyboard_interrupt(self):
        """Test main handles KeyboardInterrupt."""
        with patch.object(_cli_mod, "create_parser") as mock_parser:
            mock_parser.return_value.parse_args.return_value = argparse.Namespace(command="store")
            with patch.object(_cli_mod.asyncio, "run", side_effect=KeyboardInterrupt):
                with pytest.raises(SystemExit) as exc_info:
                    main_func()
                assert exc_info.value.code == 130

    def test_main_unexpected_exception(self):
        """Test main handles unexpected exception."""
        with patch.object(_cli_mod, "create_parser") as mock_parser:
            mock_parser.return_value.parse_args.return_value = argparse.Namespace(command="store")
            with patch.object(_cli_mod.asyncio, "run", side_effect=RuntimeError("crash")):
                with pytest.raises(SystemExit) as exc_info:
                    main_func()
                assert exc_info.value.code == 1

    def test_main_success(self):
        """Test main with successful execution."""
        with patch.object(_cli_mod, "create_parser") as mock_parser:
            mock_parser.return_value.parse_args.return_value = argparse.Namespace(command="store")
            with patch.object(_cli_mod.asyncio, "run", return_value=0):
                with pytest.raises(SystemExit) as exc_info:
                    main_func()
                assert exc_info.value.code == 0
