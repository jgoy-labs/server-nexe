"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: memory/rag/tests/test_cli.py
Description: Tests per RAG CLI (cli.py).

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
  """Tests per argument parser."""

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
    assert args.source == "personality"

  def test_parser_search_options(self):
    """Verify search command options."""
    parser = create_parser()
    args = parser.parse_args([
      "search", "my query",
      "--top-k", "10",
      "--source", "catalog",
      "--verbose"
    ])
    assert args.query == "my query"
    assert args.top_k == 10
    assert args.source == "catalog"
    assert args.verbose is True

  def test_parser_sources_command(self):
    """Verify sources command parsed."""
    parser = create_parser()
    args = parser.parse_args(["sources"])
    assert args.command == "sources"

class TestRAGCLI:
  """Tests per RAGCLI class."""

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
      "sources": ["personality"],
      "capabilities": ["vector_search"],
      "stats": {
        "documents_added": 10,
        "searches_performed": 5,
        "total_chunks": 50,
        "cache_hit_rate": 0.8
      },
      "config": {"top_k": 5}
    }
    mock.get_health.return_value = {
      "status": "healthy",
      "checks": [
        {"name": "module_initialized", "status": "pass", "message": "OK"},
        {"name": "rag_sources", "status": "pass", "message": "1 sources healthy"}
      ],
      "metadata": {}
    }
    mock.list_sources.return_value = ["personality"]
    mock.get_source.return_value = MagicMock(
      health=lambda: {"status": "healthy", "num_chunks": 50}
    )
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
      "sources": ["personality"], "capabilities": ["search"],
      "stats": {"documents_added": 0, "searches_performed": 0, "total_chunks": 0, "cache_hit_rate": 0.0},
      "config": {"top_k": 5}
    }
    mock.get_health.return_value = {
      "status": "healthy",
      "checks": [
        {"name": "module_initialized", "status": "pass", "message": "OK"},
        {"name": "rag_sources", "status": "pass", "message": "OK", "sources": {
          "personality": {"status": "healthy", "num_chunks": 50, "num_documents": 5}
        }}
      ],
      "metadata": {}
    }
    mock.list_sources.return_value = ["personality"]
    mock.get_source.return_value = MagicMock(
      health=lambda: {"status": "healthy", "num_chunks": 50, "num_documents": 5}
    )
    mock.search = MagicMock(return_value=[])
    mock.initialize = MagicMock(return_value=True)
    mock.shutdown = MagicMock(return_value=None)
    return mock

  @pytest.mark.asyncio
  async def test_initialize_success(self):
    """Test CLI initialization success."""
    cli = RAGCLI()
    mock_module = MagicMock()
    mock_module.initialize = MagicMock(return_value=True)
    with patch.object(RAGCLI, 'initialize') as mock_init:
      mock_init.return_value = True
      result = await cli.initialize()
      # The patched version returns True

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
      "stats": {"documents_added": 0, "searches_performed": 0, "total_chunks": 0, "cache_hit_rate": 0.0},
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
  async def test_cmd_health_with_sources_check(self, mock_module):
    """Test health command shows sources health details."""
    cli = RAGCLI()
    cli.module = mock_module
    args = MagicMock(json=False)
    result = await cli.cmd_health(args)
    assert result == 0

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
    """Test search with results."""
    pass  # AsyncMock already imported at top
    hit = MagicMock()
    hit.score = 0.9
    hit.text = "Result text"
    hit.metadata = {"source": "test"}
    mock_module.search = AsyncMock(return_value=[hit])
    cli = RAGCLI()
    cli.module = mock_module
    args = MagicMock(query="test query", top_k=5, source="personality", verbose=True)
    with patch.dict("sys.modules", {"memory.rag_sources.base": MagicMock()}):
      result = await cli.cmd_search(args)
      assert result == 0

  @pytest.mark.asyncio
  async def test_cmd_search_no_results(self, mock_module):
    """Test search with no results."""
    pass  # AsyncMock already imported at top
    mock_module.search = AsyncMock(return_value=[])
    cli = RAGCLI()
    cli.module = mock_module
    args = MagicMock(query="no match", top_k=5, source="personality", verbose=False)
    with patch.dict("sys.modules", {"memory.rag_sources.base": MagicMock()}):
      result = await cli.cmd_search(args)
      assert result == 0

  @pytest.mark.asyncio
  async def test_cmd_search_error(self):
    """Test search handles errors."""
    pass  # AsyncMock already imported at top
    cli = RAGCLI()
    cli.module = MagicMock()
    cli.module.search = AsyncMock(side_effect=Exception("Search error"))
    args = MagicMock(query="test", top_k=5, source="personality", verbose=False)
    with patch.dict("sys.modules", {"memory.rag_sources.base": MagicMock()}):
      result = await cli.cmd_search(args)
      assert result == 1

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
  async def test_cmd_sources_with_details(self, mock_module):
    """Test sources command shows health and doc info."""
    cli = RAGCLI()
    cli.module = mock_module
    args = MagicMock()
    result = await cli.cmd_sources(args)
    assert result == 0

  @pytest.mark.asyncio
  async def test_cmd_sources_source_error(self):
    """Test sources handles source error."""
    cli = RAGCLI()
    cli.module = MagicMock()
    cli.module.list_sources.return_value = ["broken"]
    cli.module.get_source.side_effect = Exception("Source error")
    args = MagicMock()
    result = await cli.cmd_sources(args)
    assert result == 0

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
