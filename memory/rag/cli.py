"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: memory/rag/cli.py
Description: Command-line interface for the RAG module (info, health, search, sources).

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import asyncio
import argparse
import sys
import logging
import json
import os
from typing import Optional

from .module import RAGModule
from core.version import __version__

logging.basicConfig(
  level=logging.INFO,
  format="%(message)s"
)
logger = logging.getLogger(__name__)

class RAGCLI:
  """CLI interface for RAG Module"""

  def __init__(self) -> None:
    self.module: Optional[RAGModule] = None

  def _require_module(self) -> RAGModule:
    """Returns self.module or raises RuntimeError if not initialized.

    Used in cmd_* to give an explicit error instead of an opaque
    AttributeError when someone calls a cmd without initialize().
    """
    if self.module is None:
      raise RuntimeError("RAG not initialized — must await RAGCLI.initialize() before invoking cmd_*")
    return self.module

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
      info = self._require_module().get_info()

      logger.info("\nRAG Module Info")
      logger.info("=" * 60)
      logger.info("ID:     %s", info.get("module_id", "N/A"))
      logger.info("Name:    %s", info.get("name", "N/A"))
      logger.info("Version:   %s", info.get("version", "N/A"))
      logger.info("Description: %s", info.get("description", "N/A"))
      logger.info("Initialized: %s", info.get("initialized", False))
      logger.info("\nSources:")
      sources = info.get("sources", [])
      if sources:
        for source in sources:
          logger.info(" - %s", source)
      else:
        logger.info(" (no sources loaded)")
      logger.info("\nCapabilities:")
      for cap in info.get("capabilities", []):
        logger.info(" - %s", cap)
      logger.info("\nStats:")
      stats = info.get("stats", {})
      logger.info(" Searches performed: %s", stats.get("searches_performed", 0))
      logger.info("\nConfig:")
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
      health = self._require_module().get_health()

      status = health.get("status", "unknown")
      status_icon = {
        "healthy": "[OK]",
        "degraded": "[WARN]",
        "unhealthy": "[FAIL]"
      }.get(status, "[??]")

      logger.info("\nRAG Module Health")
      logger.info("=" * 60)
      logger.info("Status: %s %s", status_icon, status.upper())
      logger.info("\nChecks:")

      checks = health.get("checks", [])
      for check in checks:
        check_status = check.get("status", "unknown")
        check_icon = {
          "pass": "[OK]",  # nosec B105: dict key 'pass' is health-check status keyword (verb), not a password literal
          "warn": "[WARN]",
          "fail": "[FAIL]"
        }.get(check_status, "[??]")
        logger.info(" %s %s: %s", check_icon, check.get("name", "?"), check.get("message", ""))

      sources_check = next((c for c in checks if c.get("name") == "rag_sources"), None)
      if sources_check and "sources" in sources_check:
        logger.info("\nSources:")
        for source_name in sources_check["sources"]:
          logger.info(" - %s", source_name)

      if args.json:
        logger.info("\nJSON Output:")
        logger.info(json.dumps(health, indent=2, default=str))

      return 0 if status == "healthy" else 1

    except Exception as e:
      logger.error("Health check error: %s", e)
      return 1

  async def cmd_search(self, args) -> int:
    """
    Perform a test search, through the same sources the chat uses.

    ADR-008 E2: `RAGModule.search` asks `source_for(name)` with the real
    MemoryAPI, so what this prints is what the turn would retrieve from that
    source. Without `--source` every listed source is searched in turn.

    Returns:
      0 if success, 1 if error
    """
    try:
      module = self._require_module()
      query = args.query
      top_k = args.top_k
      sources = [args.source] if args.source else module.list_sources()

      logger.info("\nRAG Search")
      logger.info("=" * 60)
      logger.info("Query: %s", query)
      logger.info("Top K: %s", top_k)
      logger.info("Lang: %s", args.lang)
      logger.info("Sources: %s\n", ", ".join(sources))

      found = 0
      for source in sources:
        results = await module.search(query, source=source, top_k=top_k, lang=args.lang)
        if not results:
          continue
        found += len(results)
        logger.info("%s (%s):", source, len(results))
        logger.info("-" * 60)
        for i, hit in enumerate(results, 1):
          score = getattr(hit, 'score', 0.0)
          text = getattr(hit, 'text', None) or str(hit)
          metadata = getattr(hit, 'metadata', {})

          logger.info("%s. [%.3f] %s", i, score, text[:100] + "..." if len(text) > 100 else text)
          if metadata and args.verbose:
            logger.info("  Metadata: %s", metadata)

      if not found:
        logger.info("No results found.")
      return 0

    except Exception as e:
      logger.error("Search error: %s", e)
      return 1

  async def cmd_sources(self, args) -> int:
    """
    List the sources the chat retrieves from (system + registered).

    Returns:
      0 if success, 1 if error
    """
    try:
      sources = self._require_module().list_sources()

      logger.info("\nRAG Sources")
      logger.info("=" * 60)

      if not sources:
        logger.info("No sources registered.")
        return 0

      for source_name in sources:
        logger.info(" - %s", source_name)

      return 0

    except Exception as e:
      logger.error("Sources error: %s", e)
      return 1

def create_parser() -> argparse.ArgumentParser:
  """Create argument parser for RAG CLI"""
  parser = argparse.ArgumentParser(
    prog="rag",
    description=f"server-nexe {__version__} - RAG Module CLI",
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
    help="Cap on results per source (default: 5; a source never returns more than its own tuned top_k)"
  )
  search_parser.add_argument(
    "-s", "--source",
    type=str,
    default=None,
    help="RAG source to search (default: every source listed by 'sources')"
  )
  search_parser.add_argument(
    "-l", "--lang",
    type=str,
    default=os.getenv("NEXE_LANG", "en"),
    help="Query language; user_knowledge filters by it (default: $NEXE_LANG or en)"
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
