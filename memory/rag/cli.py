"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: memory/rag/cli.py
Description: %s", info.get("description", "N/A"))

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import asyncio
import argparse
import sys
import logging
import json
from typing import Optional

from .module import RAGModule

logging.basicConfig(
  level=logging.INFO,
  format="%(message)s"
)
logger = logging.getLogger(__name__)

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
        logger.error("Failed to initialize RAG module")
        return False
      return True
    except Exception as e:
      logger.error("Initialization error: %s", e)
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
      logger.info("RAG Module Info")
      logger.info("=" * 60)
      logger.info("ID:     %s", info.get("module_id", "N/A"))
      logger.info("Name:    %s", info.get("name", "N/A"))
      logger.info("Version:   %s", info.get("version", "N/A"))
      logger.info("Description: %s", info.get("description", "N/A"))
      logger.info("Initialized: %s", info.get("initialized", False))
      logger.info("")
      logger.info("Sources:")
      sources = info.get("sources", [])
      if sources:
        for source in sources:
          logger.info(" - %s", source)
      else:
        logger.info(" (no sources loaded)")
      logger.info("")
      logger.info("Capabilities:")
      for cap in info.get("capabilities", []):
        logger.info(" - %s", cap)
      logger.info("")
      logger.info("Stats:")
      stats = info.get("stats", {})
      logger.info(" Documents added:   %s", stats.get("documents_added", 0))
      logger.info(" Searches performed: %s", stats.get("searches_performed", 0))
      logger.info(" Total chunks:    %s", stats.get("total_chunks", 0))
      logger.info(" Cache hit rate:   %.1f%%", stats.get("cache_hit_rate", 0) * 100)
      logger.info("")
      logger.info("Config:")
      config = info.get("config", {})
      for key, value in config.items():
        logger.info(" %s: %s", key, value)

      return 0

    except Exception as e:
      logger.error("Info error: %s", e)
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
      logger.info("RAG Module Health")
      logger.info("=" * 60)
      logger.info("Status: %s %s", status_icon, status.upper())
      logger.info("")
      logger.info("Checks:")

      checks = health.get("checks", [])
      for check in checks:
        check_status = check.get("status", "unknown")
        check_icon = {
          "pass": "[OK]",
          "warn": "[WARN]",
          "fail": "[FAIL]"
        }.get(check_status, "[??]")
        logger.info(" %s %s: %s", check_icon, check.get("name", "?"), check.get("message", ""))

      sources_check = next((c for c in checks if c.get("name") == "rag_sources"), None)
      if sources_check and "sources" in sources_check:
        logger.info("")
        logger.info("Sources Health:")
        for source_name, source_health in sources_check["sources"].items():
          s_status = source_health.get("status", "unknown")
          s_icon = {
            "healthy": "[OK]",
            "degraded": "[WARN]",
            "unhealthy": "[FAIL]"
          }.get(s_status, "[??]")
          logger.info(" %s %s", s_icon, source_name)
          if "num_chunks" in source_health:
            logger.info("   Chunks: %s", source_health["num_chunks"])
          if "num_documents" in source_health:
            logger.info("   Documents: %s", source_health["num_documents"])

      if args.json:
        logger.info("")
        logger.info("JSON Output:")
        logger.info(json.dumps(health, indent=2, default=str))

      return 0 if status == "healthy" else 1

    except Exception as e:
      logger.error("Health check error: %s", e)
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
      logger.info("RAG Search")
      logger.info("=" * 60)
      logger.info("Query: %s", query)
      logger.info("Top K: %s", top_k)
      logger.info("Source: %s", source)
      logger.info("")

      request = SearchRequest(query=query, top_k=top_k)
      results = await self.module.search(request, source=source)

      if not results:
        logger.info("No results found.")
        return 0

      logger.info("Results (%s):", len(results))
      logger.info("-" * 60)

      for i, hit in enumerate(results, 1):
        score = getattr(hit, 'score', 0.0)
        text = getattr(hit, 'text', str(hit))
        metadata = getattr(hit, 'metadata', {})

        logger.info("%s. [%.3f] %s", i, score, text[:100] + "..." if len(text) > 100 else text)
        if metadata and args.verbose:
          logger.info("  Metadata: %s", metadata)

      return 0

    except Exception as e:
      logger.error("Search error: %s", e)
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
      logger.info("RAG Sources")
      logger.info("=" * 60)

      if not sources:
        logger.info("No sources registered.")
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

          logger.info("%s %s", status_icon, source_name)
          if "num_documents" in health:
            logger.info("  Documents: %s", health["num_documents"])
          if "num_chunks" in health:
            logger.info("  Chunks: %s", health["num_chunks"])
        except Exception as e:
          logger.info("[??] %s - Error: %s", source_name, e)

      return 0

    except Exception as e:
      logger.error("Sources error: %s", e)
      return 1

def create_parser() -> argparse.ArgumentParser:
  """Create argument parser for RAG CLI"""
  parser = argparse.ArgumentParser(
    prog="rag",
    description="Nexe 0.8 - RAG Module CLI",
    formatter_class=argparse.RawDescriptionHelpFormatter
  )

  subparsers = parser.add_subparsers(dest="command", help="Available commands")

  subparsers.add_parser(
    "info",
    help="Show RAG module info and configuration"
  )

  health_parser = subparsers.add_parser(
    "health",
    help="Show RAG module health status"
  )
  health_parser.add_argument(
    "--json",
    action="store_true",
    help="Output health in JSON format"
  )

  search_parser = subparsers.add_parser(
    "search",
    help="Perform a test search"
  )
  search_parser.add_argument(
    "query",
    type=str,
    help="Search query"
  )
  search_parser.add_argument(
    "-k", "--top-k",
    type=int,
    default=5,
    help="Number of results (default: 5)"
  )
  search_parser.add_argument(
    "-s", "--source",
    type=str,
    default="personality",
    help="RAG source to search (default: personality)"
  )
  search_parser.add_argument(
    "-v", "--verbose",
    action="store_true",
    help="Show metadata for each result"
  )

  subparsers.add_parser(
    "sources",
    help="List available RAG sources"
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
      logger.error("No command specified. Use --help for usage.")
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
    logger.info("\nInterrupted by user")
    sys.exit(130)
  except Exception as e:
    logger.error("Unexpected error: %s", e)
    sys.exit(1)

if __name__ == "__main__":
  main()
