"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: memory/memory/cli/rag_viewer.py
Description: No description available.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

from core.cli.output import NEXE_LOGO

# Configurable CLI timeout via environment variable
CLI_QDRANT_TIMEOUT = float(os.getenv('NEXE_CLI_QDRANT_TIMEOUT', '5.0'))

RAG_LOG_PATH = Path(os.environ.get("NEXE_LOGS_DIR", str(Path.home() / "Nexe-Logs"))) / "rag.log"
FALLBACK_PATHS = [
  Path(__file__).parent.parent.parent.parent.parent / "storage" / "logs" / "rag.log",
  Path("/tmp/nexe-logs/rag.log"),
]

def find_log_path() -> Path:
  """Troba el path del log RAG."""
  if RAG_LOG_PATH.exists():
    return RAG_LOG_PATH

  for path in FALLBACK_PATHS:
    if path.exists():
      return path

  RAG_LOG_PATH.parent.mkdir(exist_ok=True)
  RAG_LOG_PATH.touch()
  return RAG_LOG_PATH

def show_stats():
  """Display RAG statistics."""
  import asyncio

  async def _get_stats():
    try:
      from memory.memory import MemoryModule
      from memory.memory.rag_logger import get_rag_logger

      module = MemoryModule.get_instance()
      await module.initialize()

      stats = {}

      if module._persistence:
        sqlite_stats = await module._persistence.get_stats()
        stats["sqlite"] = sqlite_stats

      if module._flash_memory:
        flash_stats = await module._flash_memory.get_stats()
        stats["flash"] = flash_stats

      if module._persistence and module._persistence._qdrant_available:
        import httpx
        async with httpx.AsyncClient(timeout=CLI_QDRANT_TIMEOUT) as client:
          response = await client.get(
            f"{module._persistence.qdrant_url}/collections/{module._persistence.collection_name}"
          )
          if response.status_code == 200:
            data = response.json()
            result = data.get("result", {})
            config = result.get("config", {}).get("params", {}).get("vectors", {})
            stats["qdrant"] = {
              "collection": module._persistence.collection_name,
              "vectors": result.get("points_count", 0),
              "dimensions": config.get("size", 768),
              "status": result.get("status", "unknown"),
            }

      rag_log = get_rag_logger()
      rag_log.stats_summary(stats)

      return stats

    except Exception as e:
      return {"error": str(e)}

  stats = asyncio.run(_get_stats())

  print("\n" + "═" * 60)
  print("📊 Nexe RAG STATISTICS")
  print("═" * 60)

  if "error" in stats:
    print(f"❌ Error: {stats['error']}")
    return

  if "sqlite" in stats:
    s = stats["sqlite"]
    print(f"\n🗄️ SQLite:")
    print(f"  Total entries: {s.get('total_entries', 0)}")
    print(f"  Episodic: {s.get('episodic_count', 0)}")
    print(f"  Semantic: {s.get('semantic_count', 0)}")

  if "qdrant" in stats:
    q = stats["qdrant"]
    print(f"\n🔷 Qdrant:")
    print(f"  Collection: {q.get('collection', 'nexe_memory')}")
    print(f"  Vectors: {q.get('vectors', 0)}")
    print(f"  Dimensions: {q.get('dimensions', 768)}")
    print(f"  Status: {q.get('status', 'unknown')}")

  if "flash" in stats:
    f = stats["flash"]
    print(f"\n⚡ FlashMemory:")
    print(f"  Cached entries: {f.get('total_entries', 0)}")
    print(f"  Expired pending: {f.get('expired_pending', 0)}")

  print("\n" + "═" * 60)
  print(f"📋 Log path: {find_log_path()}")
  print("═" * 60 + "\n")

def main():
  parser = argparse.ArgumentParser(
    description="Veure logs RAG/Memory de Nexe en temps real"
  )
  parser.add_argument(
    "--lines", "-n",
    type=int,
    default=30,
    help="Number of lines to show initially (default: 30)"
  )
  parser.add_argument(
    "--clear", "-c",
    action="store_true",
    help="Clear the log before following"
  )
  parser.add_argument(
    "--path", "-p",
    action="store_true",
    help="Show log path and exit"
  )
  parser.add_argument(
    "--stats", "-s",
    action="store_true",
    help="Show RAG statistics and exit"
  )
  args = parser.parse_args()

  log_path = find_log_path()

  if args.path:
    print(log_path)
    return

  if args.stats:
    show_stats()
    return

  if args.clear:
    log_path.write_text("")
    print(f"🗑️ RAG log netejat: {log_path}")

  GREEN = "\033[32m"
  GRAY = "\033[90m"
  RESET = "\033[0m"
  print(f"{GREEN}{NEXE_LOGO}{RESET}")
  print(f"{GRAY}Mode: RAG Log Viewer | Log: {log_path}{RESET}")
  print()

  try:
    subprocess.run(
      ["tail", "-n", str(args.lines), "-f", str(log_path)],
      check=True
    )
  except KeyboardInterrupt:
    print("\n\n👋 Sortint del visor de logs RAG")
  except FileNotFoundError:
    _python_tail(log_path, args.lines)

def _python_tail(log_path: Path, lines: int):
  """Fallback a Python pur si tail no existeix."""
  import time

  if log_path.exists():
    content = log_path.read_text()
    last_lines = content.split('\n')[-lines:]
    for line in last_lines:
      print(line)

  try:
    with open(log_path, 'r') as f:
      f.seek(0, 2)
      while True:
        line = f.readline()
        if line:
          print(line, end='')
        else:
          time.sleep(0.1)
  except KeyboardInterrupt:
    print("\n\n👋 Sortint del visor de logs RAG")

if __name__ == "__main__":
  main()