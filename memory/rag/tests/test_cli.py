"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: memory/rag/tests/test_cli.py
Description: Tests per RAG CLI (cli.py).

www.jgoy.net
────────────────────────────────────
"""

import pytest
from unittest.mock import MagicMock

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
