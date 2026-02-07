"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: memory/rag/cli.py
Description: %s", info.get("description", "N/A"))

www.jgoy.net
────────────────────────────────────
"""

import asyncio
import argparse
import sys
import logging
import json
from typing import Optional

from .module import RAGModule
from personality.i18n.resolve import t_modular

logging.basicConfig(
  level=logging.INFO,
  format="%(message)s"
)
logger = logging.getLogger(__name__)

def _t(key: str, fallback: str, **kwargs) -> str:
  return t_modular(f"rag.cli.{key}", fallback, **kwargs)

class RAGCLI:
  """CLI interface for RAG Module"""

  def __init__(self):
    self.module: Optional[RAGModule] = None

  async def initialize(self) -> bool:
    """Initialize RAG module"""
    try:
      self.module = RAGModule.get_instance()
      success = await self.module.initialize()
      if not success:
        logger.error(_t("init_failed", "Failed to initialize RAG module"))
        return False
      return True
    except Exception as e:
      logger.error(_t("init_error", "Initialization error: {error}", error=str(e)))
      return False

  async def shutdown(self):
    """Shutdown RAG module"""
    if self.module:
      await self.module.shutdown()

  async def cmd_info(self, args) -> int:
    """
    Show RAG module info and configuration.

    Returns:
      0 if success, 1 if error
    """
    try:
      info = self.module.get_info()

      logger.info("")
      logger.info(_t("info_title", "RAG Module Info"))
      logger.info("=" * 60)
      logger.info(_t("info_id", "ID:     {value}", value=info.get("module_id", "N/A")))
      logger.info(_t("info_name", "Name:    {value}", value=info.get("name", "N/A")))
      logger.info(_t("info_version", "Version:   {value}", value=info.get("version", "N/A")))
      logger.info(_t("info_description", "Description: {value}", value=info.get("description", "N/A")))
      logger.info(_t("info_initialized", "Initialized: {value}", value=info.get("initialized", False)))
      logger.info("")
      logger.info(_t("sources_title", "Sources:"))
      sources = info.get("sources", [])
      if sources:
        for source in sources:
          logger.info(_t("list_item", " - {item}", item=source))
      else:
        logger.info(_t("no_sources_loaded", " (no sources loaded)"))
      logger.info("")
      logger.info(_t("capabilities_title", "Capabilities:"))
      for cap in info.get("capabilities", []):
        logger.info(_t("list_item", " - {item}", item=cap))
      logger.info("")
      logger.info(_t("stats_title", "Stats:"))
      stats = info.get("stats", {})
      logger.info(_t("stats_documents_added", " Documents added:   {count}", count=stats.get("documents_added", 0)))
      logger.info(_t("stats_searches_performed", " Searches performed: {count}", count=stats.get("searches_performed", 0)))
      logger.info(_t("stats_total_chunks", " Total chunks:    {count}", count=stats.get("total_chunks", 0)))
      logger.info(_t("stats_cache_hit_rate", " Cache hit rate:   {rate:.1f}%", rate=stats.get("cache_hit_rate", 0) * 100))
      logger.info("")
      logger.info(_t("config_title", "Config:"))
      config = info.get("config", {})
      for key, value in config.items():
        logger.info(_t("config_item", " {key}: {value}", key=key, value=value))

      return 0

    except Exception as e:
      logger.error(_t("info_error", "Info error: {error}", error=str(e)))
      return 1

  async def cmd_health(self, args) -> int:
    """
    Show RAG module health status.

    Returns:
      0 if healthy, 1 if unhealthy
    """
    try:
      health = self.module.get_health()

      status = health.get("status", "unknown")
      status_icon = {
        "healthy": "[OK]",
        "degraded": "[WARN]",
        "unhealthy": "[FAIL]"
      }.get(status, "[??]")

      logger.info("")
      logger.info(_t("health_title", "RAG Module Health"))
      logger.info("=" * 60)
      logger.info(_t("health_status", "Status: {icon} {status}", icon=status_icon, status=status.upper()))
      logger.info("")
      logger.info(_t("health_checks", "Checks:"))

      checks = health.get("checks", [])
      for check in checks:
        check_status = check.get("status", "unknown")
        check_icon = {
          "pass": "[OK]",
          "warn": "[WARN]",
          "fail": "[FAIL]"
        }.get(check_status, "[??]")
        logger.info(_t(
          "health_check_item",
          " {icon} {name}: {message}",
          icon=check_icon,
          name=check.get("name", "?"),
          message=check.get("message", "")
        ))

      sources_check = next((c for c in checks if c.get("name") == "rag_sources"), None)
      if sources_check and "sources" in sources_check:
        logger.info("")
        logger.info(_t("health_sources", "Sources Health:"))
        for source_name, source_health in sources_check["sources"].items():
          s_status = source_health.get("status", "unknown")
          s_icon = {
            "healthy": "[OK]",
            "degraded": "[WARN]",
            "unhealthy": "[FAIL]"
          }.get(s_status, "[??]")
          logger.info(_t(
            "health_source_item",
            " {icon} {name}",
            icon=s_icon,
            name=source_name
          ))
          if "num_chunks" in source_health:
            logger.info(_t("health_source_chunks", "   Chunks: {count}", count=source_health["num_chunks"]))
          if "num_documents" in source_health:
            logger.info(_t("health_source_documents", "   Documents: {count}", count=source_health["num_documents"]))

      if args.json:
        logger.info("")
        logger.info(_t("health_json_output", "JSON Output:"))
        logger.info(json.dumps(health, indent=2, default=str))

      return 0 if status == "healthy" else 1

    except Exception as e:
      logger.error(_t("health_error", "Health check error: {error}", error=str(e)))
      return 1

  async def cmd_search(self, args) -> int:
    """
    Perform a test search.

    Returns:
      0 if success, 1 if error
    """
    try:
      from memory.rag_sources.base import SearchRequest

      query = args.query
      top_k = args.top_k
      source = args.source

      logger.info("")
      logger.info(_t("search_title", "RAG Search"))
      logger.info("=" * 60)
      logger.info(_t("search_query", "Query: {query}", query=query))
      logger.info(_t("search_top_k", "Top K: {top_k}", top_k=top_k))
      logger.info(_t("search_source", "Source: {source}", source=source))
      logger.info("")

      request = SearchRequest(query=query, top_k=top_k)
      results = await self.module.search(request, source=source)

      if not results:
        logger.info(_t("search_no_results", "No results found."))
        return 0

      logger.info(_t("search_results", "Results ({count}):", count=len(results)))
      logger.info("-" * 60)

      for i, hit in enumerate(results, 1):
        score = getattr(hit, 'score', 0.0)
        text = getattr(hit, 'text', str(hit))
        metadata = getattr(hit, 'metadata', {})

        logger.info(_t(
          "search_result_item",
          "{index}. [{score:.3f}] {text}",
          index=i,
          score=score,
          text=text[:100] + "..." if len(text) > 100 else text
        ))
        if metadata and args.verbose:
          logger.info(_t("search_metadata", "  Metadata: {metadata}", metadata=metadata))

      return 0

    except Exception as e:
      logger.error(_t("search_error", "Search error: {error}", error=str(e)))
      return 1

  async def cmd_sources(self, args) -> int:
    """
    List available RAG sources.

    Returns:
      0 if success, 1 if error
    """
    try:
      sources = self.module.list_sources()

      logger.info("")
      logger.info(_t("sources_title", "RAG Sources"))
      logger.info("=" * 60)

      if not sources:
        logger.info(_t("sources_none", "No sources registered."))
        return 0

      for source_name in sources:
        try:
          source = self.module.get_source(source_name)
          health = source.health() if hasattr(source, 'health') else {}
          status = health.get("status", "unknown")
          status_icon = {
            "healthy": "[OK]",
            "degraded": "[WARN]",
            "unhealthy": "[FAIL]"
          }.get(status, "[??]")

          logger.info(_t(
            "sources_item",
            "{icon} {name}",
            icon=status_icon,
            name=source_name
          ))
          if "num_documents" in health:
            logger.info(_t("sources_documents", "  Documents: {count}", count=health["num_documents"]))
          if "num_chunks" in health:
            logger.info(_t("sources_chunks", "  Chunks: {count}", count=health["num_chunks"]))
        except Exception as e:
          logger.info(_t(
            "sources_item_error",
            "[??] {source} - Error: {error}",
            source=source_name,
            error=e
          ))

      return 0

    except Exception as e:
      logger.error(_t("sources_error", "Sources error: {error}", error=str(e)))
      return 1

def create_parser() -> argparse.ArgumentParser:
  """Create argument parser for RAG CLI"""
  parser = argparse.ArgumentParser(
    prog="rag",
    description=_t("description", "Nexe 0.8 - RAG Module CLI"),
    formatter_class=argparse.RawDescriptionHelpFormatter
  )

  subparsers = parser.add_subparsers(dest="command", help=_t("commands_help", "Available commands"))

  subparsers.add_parser(
    "info",
    help=_t("cmd_info_help", "Show RAG module info and configuration")
  )

  health_parser = subparsers.add_parser(
    "health",
    help=_t("cmd_health_help", "Show RAG module health status")
  )
  health_parser.add_argument(
    "--json",
    action="store_true",
    help=_t("arg_health_json", "Output health in JSON format")
  )

  search_parser = subparsers.add_parser(
    "search",
    help=_t("cmd_search_help", "Perform a test search")
  )
  search_parser.add_argument(
    "query",
    type=str,
    help=_t("arg_search_query", "Search query")
  )
  search_parser.add_argument(
    "-k", "--top-k",
    type=int,
    default=5,
    help=_t("arg_search_top_k", "Number of results (default: 5)")
  )
  search_parser.add_argument(
    "-s", "--source",
    type=str,
    default="personality",
    help=_t("arg_search_source", "RAG source to search (default: personality)")
  )
  search_parser.add_argument(
    "-v", "--verbose",
    action="store_true",
    help=_t("arg_search_verbose", "Show metadata for each result")
  )

  subparsers.add_parser(
    "sources",
    help=_t("cmd_sources_help", "List available RAG sources")
  )

  return parser

async def async_main(args):
  """Async main function"""
  cli = RAGCLI()

  if not await cli.initialize():
    return 1

  try:
    if args.command == "info":
      return await cli.cmd_info(args)
    elif args.command == "health":
      return await cli.cmd_health(args)
    elif args.command == "search":
      return await cli.cmd_search(args)
    elif args.command == "sources":
      return await cli.cmd_sources(args)
    else:
      logger.error(_t("no_command", "No command specified. Use --help for usage."))
      return 1

  finally:
    await cli.shutdown()

def main():
  """Entry point for RAG CLI"""
  parser = create_parser()
  args = parser.parse_args()

  try:
    exit_code = asyncio.run(async_main(args))
    sys.exit(exit_code)
  except KeyboardInterrupt:
    logger.info(_t("interrupted", "\nInterrupted by user"))
    sys.exit(130)
  except Exception as e:
    logger.error(_t("unexpected_error", "Unexpected error: {error}", error=str(e)))
    sys.exit(1)

if __name__ == "__main__":
  main()
