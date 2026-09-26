"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: memory/rag/tests/test_cli.py
Description: Tests for RAG CLI (cli.py).

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock

from memory.rag.cli import (
  create_parser,
  RAGCLI,
)

class TestCreateParser:
  """Tests for argument parser."""

  def test_parser_created(self):
    """Verify parser is created."""
    parser = create_parser()
    assert parser is not None
    assert parser.prog == "rag"

  def test_parser_info_command(self):
    """Verify info command parsed."""
    parser = create_parser()
    args = parser.parse_args(["info"])
    assert args.command == "info"

  def test_parser_health_command(self):
    """Verify health command parsed."""
    parser = create_parser()
    args = parser.parse_args(["health"])
    assert args.command == "health"
    assert args.json is False

  def test_parser_health_json_flag(self):
    """Verify health --json flag."""
    parser = create_parser()
    args = parser.parse_args(["health", "--json"])
    assert args.json is True

  def test_parser_search_command(self):
    """Verify search command with query."""
    parser = create_parser()
    args = parser.parse_args(["search", "test query"])
    assert args.command == "search"
    assert args.query == "test query"
    assert args.top_k == 5
    assert args.source is None, "no default source: without --source every listed source is searched"
    assert args.lang

  def test_parser_search_options(self):
    """Verify search command options."""
    parser = create_parser()
    args = parser.parse_args([
      "search", "my query",
      "--top-k", "10",
      "--source", "catalog",
      "--lang", "ca",
      "--verbose"
    ])
    assert args.query == "my query"
    assert args.top_k == 10
    assert args.source == "catalog"
    assert args.lang == "ca"
    assert args.verbose is True

  def test_parser_sources_command(self):
    """Verify sources command parsed."""
    parser = create_parser()
    args = parser.parse_args(["sources"])
    assert args.command == "sources"

class TestRAGCLI:
  """Tests for RAGCLI class."""

  @pytest.fixture
  def mock_module(self):
    """Create mock RAGModule."""
    mock = MagicMock()
    mock.get_info.return_value = {
      "module_id": "TEST-123",
      "name": "rag",
      "version": "0.1",
      "description": "Test RAG",
      "initialized": True,
      "sources": ["nexe_documentation", "personal_memory", "user_knowledge"],
      "capabilities": ["source_introspection"],
      "stats": {
        "searches_performed": 5,
      },
      "config": {"top_k": 5}
    }
    mock.get_health.return_value = {
      "status": "healthy",
      "checks": [
        {"name": "module_initialized", "status": "pass", "message": "OK"},
        {"name": "rag_sources", "status": "pass", "message": "3 sources available"}
      ],
      "metadata": {}
    }
    mock.list_sources.return_value = ["nexe_documentation", "personal_memory", "user_knowledge"]
    return mock

  @pytest.fixture
  def cli_with_mock(self, mock_module):
    """Create CLI with mocked module."""
    cli = RAGCLI()
    cli.module = mock_module
    return cli

  @pytest.mark.asyncio
  async def test_cmd_info_returns_zero(self, cli_with_mock):
    """Test info command returns 0 on success."""
    args = MagicMock()
    result = await cli_with_mock.cmd_info(args)
    assert result == 0

  @pytest.mark.asyncio
  async def test_cmd_info_calls_get_info(self, cli_with_mock):
    """Test info command calls module.get_info()."""
    args = MagicMock()
    await cli_with_mock.cmd_info(args)
    cli_with_mock.module.get_info.assert_called_once()

  @pytest.mark.asyncio
  async def test_cmd_info_emits_no_empty_log_records(self, cli_with_mock, caplog):
    # MC-115: blank logger.info("") spacers emit empty LogRecords (structural
    # noise). Spacing must be folded into the adjacent message instead, so no
    # empty record is ever emitted — while the section headers stay visible.
    import logging
    args = MagicMock()
    with caplog.at_level(logging.INFO, logger="memory.rag.cli"):
      await cli_with_mock.cmd_info(args)
    assert [r for r in caplog.records if r.getMessage() == ""] == []
    assert "RAG Module Info" in caplog.text

  @pytest.mark.asyncio
  async def test_cmd_health_emits_no_empty_log_records(self, cli_with_mock, caplog):
    # MC-115: same for the health command.
    import logging
    args = MagicMock(json=False)
    with caplog.at_level(logging.INFO, logger="memory.rag.cli"):
      await cli_with_mock.cmd_health(args)
    assert [r for r in caplog.records if r.getMessage() == ""] == []
    assert "RAG Module Health" in caplog.text

  def test_no_empty_logger_info_in_source(self):
    # MC-115: the logger.info("") anti-pattern must be gone from the whole file.
    import inspect
    import memory.rag.cli as ragcli
    assert 'logger.info("")' not in inspect.getsource(ragcli)

  @pytest.mark.asyncio
  async def test_cmd_health_healthy_returns_zero(self, cli_with_mock):
    """Test health command returns 0 when healthy."""
    args = MagicMock(json=False)
    result = await cli_with_mock.cmd_health(args)
    assert result == 0

  @pytest.mark.asyncio
  async def test_cmd_health_unhealthy_returns_one(self, cli_with_mock):
    """Test health command returns 1 when unhealthy."""
    cli_with_mock.module.get_health.return_value = {
      "status": "unhealthy",
      "checks": [
        {"name": "test", "status": "fail", "message": "Error"}
      ],
      "metadata": {}
    }
    args = MagicMock(json=False)
    result = await cli_with_mock.cmd_health(args)
    assert result == 1

  @pytest.mark.asyncio
  async def test_cmd_health_calls_get_health(self, cli_with_mock):
    """Test health command calls module.get_health()."""
    args = MagicMock(json=False)
    await cli_with_mock.cmd_health(args)
    cli_with_mock.module.get_health.assert_called_once()

  @pytest.mark.asyncio
  async def test_cmd_sources_returns_zero(self, cli_with_mock):
    """Test sources command returns 0."""
    args = MagicMock()
    result = await cli_with_mock.cmd_sources(args)
    assert result == 0

  @pytest.mark.asyncio
  async def test_cmd_sources_calls_list_sources(self, cli_with_mock):
    """Test sources command calls module.list_sources()."""
    args = MagicMock()
    await cli_with_mock.cmd_sources(args)
    cli_with_mock.module.list_sources.assert_called_once()

class TestAdvertisedCommands:
  """`core/cli/router.py` advertises the rag CLI's commands; it listed
  `search, index, status` — two of which never existed. Pinned to the parser
  itself so the two cannot drift apart again (ADR-008 E2)."""

  def test_router_lists_exactly_the_parser_subcommands(self):
    import argparse
    from core.cli.router import DEFAULT_CLIS

    parser = create_parser()
    sub = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    assert sorted(DEFAULT_CLIS["rag"].commands) == sorted(sub.choices)

class TestCLIEdgeCases:
  """Tests for edge cases and error handling."""

  def test_parser_no_command(self):
    """Verify no command gives None."""
    parser = create_parser()
    args = parser.parse_args([])
    assert args.command is None

  def test_parser_search_requires_query(self):
    """Verify search requires query argument."""
    parser = create_parser()
    with pytest.raises(SystemExit):
      parser.parse_args(["search"])

  def test_parser_unknown_command(self):
    """Verify unknown command raises error."""
    parser = create_parser()
    with pytest.raises(SystemExit):
      parser.parse_args(["unknown"])

class TestCLIIntegration:
  """Integration tests for CLI."""

  def test_cli_instance_creation(self):
    """Test CLI instance can be created."""
    cli = RAGCLI()
    assert cli.module is None

  @pytest.mark.asyncio
  async def test_cli_cmd_info_error_handling(self):
    """Test info handles errors gracefully."""
    cli = RAGCLI()
    cli.module = MagicMock()
    cli.module.get_info.side_effect = Exception("Test error")

    args = MagicMock()
    result = await cli.cmd_info(args)

    assert result == 1


class TestCLICoverage:
  """Additional tests for uncovered CLI lines."""

  @pytest.fixture
  def mock_module(self):
    mock = MagicMock()
    mock.get_info.return_value = {
      "module_id": "TEST", "name": "rag", "version": "0.1",
      "description": "Test", "initialized": True,
      "sources": ["nexe_documentation"], "capabilities": ["source_introspection"],
      "stats": {"searches_performed": 0},
      "config": {"top_k": 5}
    }
    mock.get_health.return_value = {
      "status": "healthy",
      "checks": [
        {"name": "module_initialized", "status": "pass", "message": "OK"},
        {"name": "rag_sources", "status": "pass", "message": "OK",
         "sources": ["nexe_documentation", "plugin_notes"]}
      ],
      "metadata": {}
    }
    mock.list_sources.return_value = ["nexe_documentation", "plugin_notes"]
    mock.search = MagicMock(return_value=[])
    mock.initialize = MagicMock(return_value=True)
    mock.shutdown = MagicMock(return_value=None)
    return mock

  @pytest.mark.asyncio
  async def test_initialize_success(self):
    """Test CLI initialization success.

    Exercises the REAL RAGCLI.initialize(): patches RAGModule so
    get_instance() returns a module whose initialize() resolves True,
    then asserts initialize() returns True and stores the module.
    """
    cli = RAGCLI()
    mock_mod = MagicMock()
    mock_mod.initialize = AsyncMock(return_value=True)
    with patch("memory.rag.cli.RAGModule") as MockRAGModule:
      MockRAGModule.get_instance.return_value = mock_mod
      result = await cli.initialize()
      assert result is True
      assert cli.module is mock_mod
      mock_mod.initialize.assert_awaited_once()

  @pytest.mark.asyncio
  async def test_initialize_failure(self):
    """Test CLI initialize returns false on failure."""
    pass  # AsyncMock already imported at top
    cli = RAGCLI()
    mock_mod = MagicMock()
    mock_mod.initialize = AsyncMock(return_value=False)
    with patch("memory.rag.cli.RAGModule") as MockRAGModule:
      MockRAGModule.get_instance.return_value = mock_mod
      result = await cli.initialize()
      assert result is False

  @pytest.mark.asyncio
  async def test_initialize_exception(self):
    """Test CLI initialize handles exceptions."""
    pass  # AsyncMock already imported at top
    cli = RAGCLI()
    with patch("memory.rag.cli.RAGModule") as MockRAGModule:
      MockRAGModule.get_instance.side_effect = Exception("Init error")
      result = await cli.initialize()
      assert result is False

  @pytest.mark.asyncio
  async def test_shutdown_with_module(self):
    """Test CLI shutdown when module is set."""
    pass  # AsyncMock already imported at top
    cli = RAGCLI()
    cli.module = MagicMock()
    cli.module.shutdown = AsyncMock()
    await cli.shutdown()
    cli.module.shutdown.assert_called_once()

  @pytest.mark.asyncio
  async def test_shutdown_without_module(self):
    """Test CLI shutdown when module is None."""
    cli = RAGCLI()
    cli.module = None
    await cli.shutdown()  # Should not raise

  @pytest.mark.asyncio
  async def test_cmd_info_no_sources(self):
    """Test info with empty sources list."""
    cli = RAGCLI()
    cli.module = MagicMock()
    cli.module.get_info.return_value = {
      "module_id": "TEST", "name": "rag", "version": "0.1",
      "description": "Test", "initialized": True,
      "sources": [], "capabilities": [],
      "stats": {"searches_performed": 0},
      "config": {}
    }
    args = MagicMock()
    result = await cli.cmd_info(args)
    assert result == 0

  @pytest.mark.asyncio
  async def test_cmd_health_with_json(self, mock_module):
    """Test health command with --json flag."""
    cli = RAGCLI()
    cli.module = mock_module
    args = MagicMock(json=True)
    result = await cli.cmd_health(args)
    assert result == 0

  @pytest.mark.asyncio
  async def test_cmd_health_with_sources_check(self, mock_module, caplog):
    """Test health command lists the sources the rag_sources check names."""
    import logging
    cli = RAGCLI()
    cli.module = mock_module
    args = MagicMock(json=False)
    with caplog.at_level(logging.INFO, logger="memory.rag.cli"):
      result = await cli.cmd_health(args)
    assert result == 0
    assert "plugin_notes" in caplog.text

  @pytest.mark.asyncio
  async def test_cmd_health_error(self):
    """Test health command handles errors."""
    cli = RAGCLI()
    cli.module = MagicMock()
    cli.module.get_health.side_effect = Exception("Health error")
    args = MagicMock(json=False)
    result = await cli.cmd_health(args)
    assert result == 1

  @pytest.mark.asyncio
  async def test_cmd_search_success(self, mock_module):
    """Test search with results: the module is asked with the new signature."""
    hit = MagicMock()
    hit.score = 0.9
    hit.text = "Result text"
    hit.metadata = {"source": "test"}
    mock_module.search = AsyncMock(return_value=[hit])
    cli = RAGCLI()
    cli.module = mock_module
    args = MagicMock(query="test query", top_k=5, source="nexe_documentation", lang="ca", verbose=True)
    result = await cli.cmd_search(args)
    assert result == 0
    mock_module.search.assert_awaited_once_with(
      "test query", source="nexe_documentation", top_k=5, lang="ca",
    )

  @pytest.mark.asyncio
  async def test_cmd_search_no_results(self, mock_module):
    """Test search with no results."""
    mock_module.search = AsyncMock(return_value=[])
    cli = RAGCLI()
    cli.module = mock_module
    args = MagicMock(query="no match", top_k=5, source="nexe_documentation", lang="en", verbose=False)
    result = await cli.cmd_search(args)
    assert result == 0

  @pytest.mark.asyncio
  async def test_cmd_search_without_source_searches_every_listed_source(self, mock_module):
    """No --source: every source the module lists is asked, in order."""
    mock_module.search = AsyncMock(return_value=[])
    cli = RAGCLI()
    cli.module = mock_module
    args = MagicMock(query="q", top_k=3, source=None, lang="en", verbose=False)
    result = await cli.cmd_search(args)
    assert result == 0
    asked = [c.kwargs["source"] for c in mock_module.search.await_args_list]
    assert asked == ["nexe_documentation", "plugin_notes"]

  @pytest.mark.asyncio
  async def test_cmd_search_error(self):
    """Test search handles errors."""
    cli = RAGCLI()
    cli.module = MagicMock()
    cli.module.search = AsyncMock(side_effect=Exception("Search error"))
    args = MagicMock(query="test", top_k=5, source="nexe_documentation", lang="en", verbose=False)
    result = await cli.cmd_search(args)
    assert result == 1

  @pytest.mark.asyncio
  async def test_cmd_search_goes_through_source_for(self, monkeypatch, caplog):
    """ADR-008 E2, end to end with the REAL module: the CLI's search reaches
    the source `source_for()` returns — here a registered one — the same door
    the chat uses. The store is not searched for a registered name."""
    import logging
    from core.rag.registry import clear_registered_sources, register_source
    from memory.rag.module import RAGModule

    class _Hit:
      score = 0.77
      text = "answer from the registered source"
      metadata = {}

    class _Src:
      def __init__(self):
        self.queries = []

      def name(self):
        return "plugin_notes"

      async def search(self, memory, query):
        self.queries.append(query)
        return [_Hit()]

    store = MagicMock()
    store.search = AsyncMock(return_value=[])
    monkeypatch.setattr("memory.memory.api.v1.get_memory_api", AsyncMock(return_value=store))
    clear_registered_sources()
    src = _Src()
    register_source(src)
    try:
      module = RAGModule.__new__(RAGModule)
      module._initialized = True
      module._stats = {"searches_performed": 0}
      cli = RAGCLI()
      cli.module = module
      args = MagicMock(query="what", top_k=5, source="plugin_notes", lang="ca", verbose=False)
      with caplog.at_level(logging.INFO, logger="memory.rag.cli"):
        result = await cli.cmd_search(args)
    finally:
      clear_registered_sources()

    assert result == 0
    assert [q.text for q in src.queries] == ["what"]
    assert src.queries[0].lang == "ca"
    assert "answer from the registered source" in caplog.text
    store.search.assert_not_awaited()

  @pytest.mark.asyncio
  async def test_cmd_search_unknown_source_is_an_error(self, monkeypatch):
    """A name the module does not list fails (exit 1) instead of searching a
    phantom collection through source_for's generic fallback."""
    from core.rag.registry import clear_registered_sources
    from memory.rag.module import RAGModule

    store = MagicMock()
    store.search = AsyncMock(return_value=[])
    monkeypatch.setattr("memory.memory.api.v1.get_memory_api", AsyncMock(return_value=store))
    clear_registered_sources()
    module = RAGModule.__new__(RAGModule)
    module._initialized = True
    module._stats = {"searches_performed": 0}
    cli = RAGCLI()
    cli.module = module
    args = MagicMock(query="q", top_k=5, source="personality", lang="en", verbose=False)

    assert await cli.cmd_search(args) == 1
    store.search.assert_not_awaited()

  @pytest.mark.asyncio
  async def test_cmd_sources_empty(self):
    """Test sources command with no sources."""
    cli = RAGCLI()
    cli.module = MagicMock()
    cli.module.list_sources.return_value = []
    args = MagicMock()
    result = await cli.cmd_sources(args)
    assert result == 0

  @pytest.mark.asyncio
  async def test_cmd_sources_with_details(self, mock_module, caplog):
    """Test sources command prints every listed source."""
    import logging
    cli = RAGCLI()
    cli.module = mock_module
    args = MagicMock()
    with caplog.at_level(logging.INFO, logger="memory.rag.cli"):
      result = await cli.cmd_sources(args)
    assert result == 0
    assert "nexe_documentation" in caplog.text
    assert "plugin_notes" in caplog.text

  @pytest.mark.asyncio
  async def test_cmd_sources_error(self):
    """Test sources handles general error."""
    cli = RAGCLI()
    cli.module = MagicMock()
    cli.module.list_sources.side_effect = Exception("List error")
    args = MagicMock()
    result = await cli.cmd_sources(args)
    assert result == 1

  def test_async_main_info(self):
    """Test async_main with info command."""
    import asyncio
    from memory.rag.cli import async_main
    pass  # AsyncMock already imported at top

    args = MagicMock(command="info")
    with patch("memory.rag.cli.RAGCLI") as MockCLI:
      instance = MockCLI.return_value
      instance.initialize = AsyncMock(return_value=True)
      instance.cmd_info = AsyncMock(return_value=0)
      instance.shutdown = AsyncMock()
      result = asyncio.run(async_main(args))
      assert result == 0

  def test_async_main_health(self):
    import asyncio
    from memory.rag.cli import async_main
    pass  # AsyncMock already imported at top
    args = MagicMock(command="health")
    with patch("memory.rag.cli.RAGCLI") as MockCLI:
      instance = MockCLI.return_value
      instance.initialize = AsyncMock(return_value=True)
      instance.cmd_health = AsyncMock(return_value=0)
      instance.shutdown = AsyncMock()
      result = asyncio.run(async_main(args))
      assert result == 0

  def test_async_main_search(self):
    import asyncio
    from memory.rag.cli import async_main
    pass  # AsyncMock already imported at top
    args = MagicMock(command="search")
    with patch("memory.rag.cli.RAGCLI") as MockCLI:
      instance = MockCLI.return_value
      instance.initialize = AsyncMock(return_value=True)
      instance.cmd_search = AsyncMock(return_value=0)
      instance.shutdown = AsyncMock()
      result = asyncio.run(async_main(args))
      assert result == 0

  def test_async_main_sources(self):
    import asyncio
    from memory.rag.cli import async_main
    pass  # AsyncMock already imported at top
    args = MagicMock(command="sources")
    with patch("memory.rag.cli.RAGCLI") as MockCLI:
      instance = MockCLI.return_value
      instance.initialize = AsyncMock(return_value=True)
      instance.cmd_sources = AsyncMock(return_value=0)
      instance.shutdown = AsyncMock()
      result = asyncio.run(async_main(args))
      assert result == 0

  def test_async_main_no_command(self):
    import asyncio
    from memory.rag.cli import async_main
    pass  # AsyncMock already imported at top
    args = MagicMock(command=None)
    with patch("memory.rag.cli.RAGCLI") as MockCLI:
      instance = MockCLI.return_value
      instance.initialize = AsyncMock(return_value=True)
      instance.shutdown = AsyncMock()
      result = asyncio.run(async_main(args))
      assert result == 1

  def test_async_main_init_fails(self):
    import asyncio
    from memory.rag.cli import async_main
    pass  # AsyncMock already imported at top
    args = MagicMock(command="info")
    with patch("memory.rag.cli.RAGCLI") as MockCLI:
      instance = MockCLI.return_value
      instance.initialize = AsyncMock(return_value=False)
      instance.shutdown = AsyncMock()
      result = asyncio.run(async_main(args))
      assert result == 1

  def test_main_entry_point(self):
    from memory.rag.cli import main
    with patch("memory.rag.cli.create_parser") as mock_parser, \
         patch("memory.rag.cli.asyncio") as mock_asyncio:
      mock_parser.return_value.parse_args.return_value = MagicMock(command="info")
      mock_asyncio.run.return_value = 0
      with pytest.raises(SystemExit):
        main()

  def test_main_keyboard_interrupt(self):
    from memory.rag.cli import main
    with patch("memory.rag.cli.create_parser") as mock_parser, \
         patch("memory.rag.cli.asyncio") as mock_asyncio:
      mock_parser.return_value.parse_args.return_value = MagicMock(command="info")
      mock_asyncio.run.side_effect = KeyboardInterrupt
      with pytest.raises(SystemExit) as exc_info:
        main()
      assert exc_info.value.code == 130

  def test_main_unexpected_error(self):
    from memory.rag.cli import main
    with patch("memory.rag.cli.create_parser") as mock_parser, \
         patch("memory.rag.cli.asyncio") as mock_asyncio:
      mock_parser.return_value.parse_args.return_value = MagicMock(command="info")
      mock_asyncio.run.side_effect = Exception("Unexpected")
      with pytest.raises(SystemExit) as exc_info:
        main()
      assert exc_info.value.code == 1
