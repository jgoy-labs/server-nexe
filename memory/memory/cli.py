"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: memory/memory/cli.py
Description: CLI executable per Memory Module (FASE 13 MVP).

www.jgoy.net
────────────────────────────────────
"""

import asyncio
import argparse
import sys
import logging
from typing import Optional

from .module import MemoryModule
from .models.memory_entry import MemoryEntry
from .models.memory_types import MemoryType
from personality.i18n.resolve import t_modular

logging.basicConfig(
  level=logging.INFO,
  format="%(message)s"
)
logger = logging.getLogger(__name__)

def _t(key: str, fallback: str, **kwargs) -> str:
  return t_modular(f"memory.cli.{key}", fallback, **kwargs)

class MemoryCLI:
  """CLI interface for Memory Module"""

  def __init__(self):
    self.module: Optional[MemoryModule] = None

  async def initialize(self) -> bool:
    """Initialize Memory module"""
    try:
      self.module = MemoryModule.get_instance()
      success = await self.module.initialize()
      if not success:
        logger.error(_t("init_failed", "Failed to initialize Memory module"))
        return False
      return True
    except Exception as e:
      logger.error(_t("init_error", "Initialization error: {error}", error=str(e)))
      return False

  async def shutdown(self):
    """Shutdown Memory module"""
    if self.module:
      await self.module.shutdown()

  async def cmd_store(self, args) -> int:
    """
    Store content to Memory.

    Args:
      args: Parsed arguments with content, type, source, ttl

    Returns:
      0 if success, 1 if error
    """
    try:
      try:
        entry_type = MemoryType(args.type)
      except ValueError:
        logger.error(_t("invalid_entry_type", "Invalid entry type: {type}", type=args.type))
        valid_types = ", ".join([t.value for t in MemoryType])
        logger.error(_t("valid_types", "  Valid types: {types}", types=valid_types))
        return 1

      entry = MemoryEntry(
        entry_type=entry_type,
        content=args.content,
        source=args.source,
        ttl_seconds=args.ttl
      )

      if not self.module._pipeline:
        logger.error(_t("pipeline_not_initialized", "Pipeline not initialized"))
        return 1

      success = await self.module._pipeline.ingest(entry)

      if success:
        logger.info(_t("store_success", "Memory stored: {id}", id=entry.id))
        logger.info(_t("store_type", "  Type: {type}", type=entry.entry_type.value))
        logger.info(_t("store_source", "  Source: {source}", source=entry.source))
        logger.info(_t("store_content", "  Content: {content}...", content=entry.content[:100]))
        return 0
      else:
        logger.error(_t("store_failed", "Failed to store memory (duplicate?)"))
        return 1

    except Exception as e:
      logger.error(_t("store_error", "Store error: {error}", error=str(e)))
      return 1

  async def cmd_recall(self, args) -> int:
    """
    Recall memories from Memory.

    Args:
      args: Parsed arguments with limit, type, safe_mode

    Returns:
      0 if success, 1 if error
    """
    try:
      if not self.module._ram_context:
        logger.error(_t("ram_not_initialized", "RAMContext not initialized"))
        return 1

      if args.type:
        try:
          entry_type = MemoryType(args.type)
        except ValueError:
          logger.error(_t("invalid_entry_type", "Invalid entry type: {type}", type=args.type))
          return 1

        entries = await self.module._ram_context.get_recent_by_type(
          entry_type=entry_type,
          limit=args.limit
        )

        logger.info(_t(
          "recall_title",
          "\n📚 Memory Recall - {type} ({count} entries)",
          type=entry_type.value,
          count=len(entries)
        ))
        logger.info("=" * 60)

        for i, entry in enumerate(entries, 1):
          content = entry.content
          if args.safe_mode and len(content) > 200:
            content = content[:200] + "..."
          logger.info(_t(
            "recall_entry_header",
            "\n{index}. [{source}] {id}",
            index=i,
            source=entry.source,
            id=entry.id
          ))
          logger.info(_t("recall_entry_content", "  {content}", content=content))

      else:
        context = await self.module._ram_context.to_context_string(
          limit=args.limit,
          safe_mode=args.safe_mode
        )

        logger.info(_t("context_title", "\n📚 Memory Context"))
        logger.info("=" * 60)
        logger.info(context)

      return 0

    except Exception as e:
      logger.error(_t("recall_error", "Recall error: {error}", error=str(e)))
      return 1

  async def cmd_stats(self, args) -> int:
    """
    Show Memory statistics.

    Returns:
      0 if success, 1 if error
    """
    try:
      if not self.module._ram_context:
        logger.error(_t("ram_not_initialized", "RAMContext not initialized"))
        return 1

      stats = await self.module._ram_context.get_stats()

      logger.info(_t("stats_title", "\n📊 Memory Statistics"))
      logger.info("=" * 60)
      logger.info(_t("stats_total_available", "Total available: {count}", count=stats['total_available']))
      logger.info(_t("stats_max_entries", "Max entries:   {count}", count=stats['max_entries']))
      logger.info(_t("stats_by_type", "\nBy type:"))
      logger.info(_t("stats_episodic", " Episodic:   {count}", count=stats['episodic_count']))
      logger.info(_t("stats_semantic", " Semantic:   {count}", count=stats['semantic_count']))

      return 0

    except Exception as e:
      logger.error(_t("stats_error", "Stats error: {error}", error=str(e)))
      return 1

  async def cmd_cleanup(self, args) -> int:
    """
    Cleanup expired memories.

    Returns:
      0 if success, 1 if error
    """
    try:
      if not self.module._flash_memory:
        logger.error(_t("flash_not_initialized", "FlashMemory not initialized"))
        return 1

      removed = await self.module._flash_memory.cleanup_expired()

      logger.info(_t(
        "cleanup_complete",
        "Cleanup completed: {count} expired entries removed",
        count=removed
      ))

      return 0

    except Exception as e:
      logger.error(_t("cleanup_error", "Cleanup error: {error}", error=str(e)))
      return 1

def create_parser() -> argparse.ArgumentParser:
  """Create argument parser for Memory CLI"""
  parser = argparse.ArgumentParser(
    prog="memory",
    description=_t("description", "Nexe 0.8 - Memory Module CLI (FASE 13 MVP)"),
    formatter_class=argparse.RawDescriptionHelpFormatter
  )

  subparsers = parser.add_subparsers(dest="command", help=_t("commands_help", "Available commands"))

  store_parser = subparsers.add_parser(
    "store",
    help=_t("cmd_store", "Store content to Memory")
  )
  store_parser.add_argument(
    "content",
    type=str,
    help=_t("arg_content", "Content to store")
  )
  store_parser.add_argument(
    "-t", "--type",
    type=str,
    default="episodic",
    choices=["episodic", "semantic"],
    help=_t("arg_type", "Entry type (default: episodic)")
  )
  store_parser.add_argument(
    "-s", "--source",
    type=str,
    default="cli",
    help=_t("arg_source", "Source identifier (default: cli)")
  )
  store_parser.add_argument(
    "--ttl",
    type=int,
    default=1800,
    help=_t("arg_ttl", "Time-to-live in seconds (default: 1800)")
  )

  recall_parser = subparsers.add_parser(
    "recall",
    help=_t("cmd_recall", "Recall memories from Memory")
  )
  recall_parser.add_argument(
    "-l", "--limit",
    type=int,
    default=20,
    help=_t("arg_limit", "Max entries to recall (default: 20)")
  )
  recall_parser.add_argument(
    "-t", "--type",
    type=str,
    choices=["episodic", "semantic"],
    help=_t("arg_recall_type", "Filter by entry type (optional)")
  )
  recall_parser.add_argument(
    "--safe-mode",
    action="store_true",
    default=True,
    help=_t("arg_safe_mode", "Truncate content to avoid info leaks (default: True)")
  )

  subparsers.add_parser(
    "stats",
    help=_t("cmd_stats", "Show Memory statistics")
  )

  subparsers.add_parser(
    "cleanup",
    help=_t("cmd_cleanup", "Cleanup expired memories")
  )

  return parser

async def async_main(args):
  """Async main function"""
  cli = MemoryCLI()

  if not await cli.initialize():
    return 1

  try:
    if args.command == "store":
      return await cli.cmd_store(args)
    elif args.command == "recall":
      return await cli.cmd_recall(args)
    elif args.command == "stats":
      return await cli.cmd_stats(args)
    elif args.command == "cleanup":
      return await cli.cmd_cleanup(args)
    else:
      logger.error(_t("no_command", "No command specified. Use --help for usage."))
      return 1

  finally:
    await cli.shutdown()

def main():
  """Entry point for Memory CLI"""
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
