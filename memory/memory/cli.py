"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: memory/memory/cli.py
Description: CLI executable per Memory Module.

www.jgoy.net · https://server-nexe.org
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

logging.basicConfig(
  level=logging.INFO,
  format="%(message)s"
)
logger = logging.getLogger(__name__)

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
        logger.error("Failed to initialize Memory module")
        return False
      return True
    except Exception as e:
      logger.error("Initialization error: %s", e)
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
        logger.error("Invalid entry type: %s", args.type)
        logger.error("  Valid types: %s", [t.value for t in MemoryType])
        return 1

      entry = MemoryEntry(
        entry_type=entry_type,
        content=args.content,
        source=args.source,
        ttl_seconds=args.ttl
      )

      if not self.module._pipeline:
        logger.error("Pipeline not initialized")
        return 1

      success = await self.module._pipeline.ingest(entry)

      if success:
        logger.info("Memory stored: %s", entry.id)
        logger.info("  Type: %s", entry.entry_type.value)
        logger.info("  Source: %s", entry.source)
        logger.info("  Content: %s...", entry.content[:100])
        return 0
      else:
        logger.error("Failed to store memory (duplicate?)")
        return 1

    except Exception as e:
      logger.error("Store error: %s", e)
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
        logger.error("RAMContext not initialized")
        return 1

      if args.type:
        try:
          entry_type = MemoryType(args.type)
        except ValueError:
          logger.error("Invalid entry type: %s", args.type)
          return 1

        entries = await self.module._ram_context.get_recent_by_type(
          entry_type=entry_type,
          limit=args.limit
        )

        logger.info("\n📚 Memory Recall - %s (%s entries)", entry_type.value, len(entries))
        logger.info("=" * 60)

        for i, entry in enumerate(entries, 1):
          content = entry.content
          if args.safe_mode and len(content) > 200:
            content = content[:200] + "..."
          logger.info("\n%s. [%s] %s", i, entry.source, entry.id)
          logger.info("  %s", content)

      else:
        context = await self.module._ram_context.to_context_string(
          limit=args.limit,
          safe_mode=args.safe_mode
        )

        logger.info("\n📚 Memory Context")
        logger.info("=" * 60)
        logger.info(context)

      return 0

    except Exception as e:
      logger.error("Recall error: %s", e)
      return 1

  async def cmd_stats(self, args) -> int:
    """
    Show Memory statistics.

    Returns:
      0 if success, 1 if error
    """
    try:
      if not self.module._ram_context:
        logger.error("RAMContext not initialized")
        return 1

      stats = await self.module._ram_context.get_stats()

      logger.info("\n📊 Memory Statistics")
      logger.info("=" * 60)
      logger.info("Total available: %s", stats['total_available'])
      logger.info("Max entries:   %s", stats['max_entries'])
      logger.info("\nBy type:")
      logger.info(" Episodic:   %s", stats['episodic_count'])
      logger.info(" Semantic:   %s", stats['semantic_count'])

      return 0

    except Exception as e:
      logger.error("Stats error: %s", e)
      return 1

  async def cmd_cleanup(self, args) -> int:
    """
    Cleanup expired memories.

    Returns:
      0 if success, 1 if error
    """
    try:
      if not self.module._flash_memory:
        logger.error("FlashMemory not initialized")
        return 1

      removed = await self.module._flash_memory.cleanup_expired()

      logger.info("Cleanup completed: %s expired entries removed", removed)

      return 0

    except Exception as e:
      logger.error("Cleanup error: %s", e)
      return 1

def create_parser() -> argparse.ArgumentParser:
  """Create argument parser for Memory CLI"""
  parser = argparse.ArgumentParser(
    prog="memory",
    description="Nexe 0.8 - Memory Module CLI",
    formatter_class=argparse.RawDescriptionHelpFormatter
  )

  subparsers = parser.add_subparsers(dest="command", help="Available commands")

  store_parser = subparsers.add_parser(
    "store",
    help="Store content to Memory"
  )
  store_parser.add_argument(
    "content",
    type=str,
    help="Content to store"
  )
  store_parser.add_argument(
    "-t", "--type",
    type=str,
    default="episodic",
    choices=["episodic", "semantic"],
    help="Entry type (default: episodic)"
  )
  store_parser.add_argument(
    "-s", "--source",
    type=str,
    default="cli",
    help="Source identifier (default: cli)"
  )
  store_parser.add_argument(
    "--ttl",
    type=int,
    default=1800,
    help="Time-to-live in seconds (default: 1800)"
  )

  recall_parser = subparsers.add_parser(
    "recall",
    help="Recall memories from Memory"
  )
  recall_parser.add_argument(
    "-l", "--limit",
    type=int,
    default=20,
    help="Max entries to recall (default: 20)"
  )
  recall_parser.add_argument(
    "-t", "--type",
    type=str,
    choices=["episodic", "semantic"],
    help="Filter by entry type (optional)"
  )
  recall_parser.add_argument(
    "--safe-mode",
    action="store_true",
    default=True,
    help="Truncate content to avoid info leaks (default: True)"
  )

  subparsers.add_parser(
    "stats",
    help="Show Memory statistics"
  )

  subparsers.add_parser(
    "cleanup",
    help="Cleanup expired memories"
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
      logger.error("No command specified. Use --help for usage.")
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
    logger.info("\nInterrupted by user")
    sys.exit(130)
  except Exception as e:
    logger.error("Unexpected error: %s", e)
    sys.exit(1)

if __name__ == "__main__":
  main()