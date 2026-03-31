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
    Show Memory statistics (v1: MemoryService + legacy).

    Returns:
      0 if success, 1 if error
    """
    try:
      # Try MemoryService first (v1)
      from .module import get_memory_service
      svc = get_memory_service()
      if svc:
        user_id = getattr(args, "user_id", "default")
        ms = await svc.stats(user_id)
        logger.info("\nMemory Statistics (v1)")
        logger.info("=" * 60)
        logger.info("  Profile:  %s", ms.profile_count)
        logger.info("  Episodic: %s", ms.episodic_count)
        logger.info("  Staging:  %s", ms.staging_count)
        logger.info("  Tombstones: %s", ms.tombstone_count)
        return 0

      # Fallback to legacy RAMContext
      if not self.module._ram_context:
        logger.error("RAMContext not initialized"); return 1
      stats = await self.module._ram_context.get_stats()
      logger.info("\nMemory Stats: total=%s max=%s episodic=%s semantic=%s",
                   stats['total_available'], stats['max_entries'],
                   stats['episodic_count'], stats['semantic_count'])
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

  def _get_svc(self):
    """Get MemoryService or None."""
    from .module import get_memory_service
    return get_memory_service()

  async def cmd_inspect(self, args) -> int:
    """Inspect a memory entry by ID."""
    try:
      svc = self._get_svc()
      if not svc:
        logger.error("MemoryService not initialized"); return 1
      for p in svc._store.get_profile(args.user_id):
        if p["id"] == args.entry_id:
          logger.info("\nProfile: %s\n  attr=%s value=%s trust=%s", args.entry_id, p["attribute"], p["value_json"], p["trust_level"])
          return 0
      for ep in svc._store.get_episodic(args.user_id, limit=10000):
        if ep["id"] == args.entry_id:
          logger.info("\nEpisodic: %s\n  content=%s importance=%s", args.entry_id, ep["content"][:200], ep["importance"])
          return 0
      logger.info("Entry not found: %s", args.entry_id); return 1
    except Exception as e:
      logger.error("Inspect error: %s", e); return 1

  async def cmd_search(self, args) -> int:
    """Search memory by query."""
    try:
      svc = self._get_svc()
      if not svc:
        logger.error("MemoryService not initialized"); return 1
      cards = await svc.recall(args.user_id, args.query, limit=args.limit)
      logger.info("\nSearch '%s' (%d found)", args.query, len(cards))
      for i, c in enumerate(cards, 1):
        logger.info("%d. [%s] %s (%.2f)", i, c.confidence, c.content[:100], c.score)
      return 0
    except Exception as e:
      logger.error("Search error: %s", e); return 1

  async def cmd_mirror(self, args) -> int:
    """Export human-readable memory mirror."""
    try:
      svc = self._get_svc()
      if not svc:
        logger.error("MemoryService not initialized"); return 1
      logger.info(await svc.export_mirror(args.user_id)); return 0
    except Exception as e:
      logger.error("Mirror error: %s", e); return 1

  async def cmd_gc(self, args) -> int:
    """Run garbage collection (dry-run available)."""
    try:
      svc = self._get_svc()
      if not svc:
        logger.error("MemoryService not initialized"); return 1
      s = await svc.stats(args.user_id)
      logger.info("\nGC user '%s': profile=%d episodic=%d staging=%d tombstones=%d",
                   args.user_id, s.profile_count, s.episodic_count, s.staging_count, s.tombstone_count)
      logger.info("  (dry-run)" if args.dry_run else "  GC daemon stub (v1)"); return 0
    except Exception as e:
      logger.error("GC error: %s", e); return 1

def create_parser() -> argparse.ArgumentParser:
  """Create argument parser for Memory CLI"""
  parser = argparse.ArgumentParser(
    prog="memory",
    description="Nexe 0.9 - Memory Module CLI",
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

  stats_p = subparsers.add_parser("stats", help="Show Memory statistics")
  stats_p.add_argument("--user-id", type=str, default="default", help="User ID")

  subparsers.add_parser("cleanup", help="Cleanup expired memories")

  # v1 debug commands
  ins_p = subparsers.add_parser("inspect", help="Inspect entry by ID")
  ins_p.add_argument("entry_id", type=str, help="Entry ID")
  ins_p.add_argument("--user-id", type=str, default="default", help="User ID")

  srch_p = subparsers.add_parser("search", help="Search memory")
  srch_p.add_argument("query", type=str, help="Search query")
  srch_p.add_argument("--user-id", type=str, default="default", help="User ID")
  srch_p.add_argument("-l", "--limit", type=int, default=10, help="Max results")

  mir_p = subparsers.add_parser("mirror", help="Export memory mirror")
  mir_p.add_argument("--user-id", type=str, default="default", help="User ID")

  gc_p = subparsers.add_parser("gc", help="Garbage collection")
  gc_p.add_argument("--dry-run", action="store_true", help="Preview only")
  gc_p.add_argument("--user-id", type=str, default="default", help="User ID")

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
    elif args.command == "inspect":
      return await cli.cmd_inspect(args)
    elif args.command == "search":
      return await cli.cmd_search(args)
    elif args.command == "mirror":
      return await cli.cmd_mirror(args)
    elif args.command == "gc":
      return await cli.cmd_gc(args)
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