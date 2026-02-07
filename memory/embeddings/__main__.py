"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: memory/embeddings/__main__.py
Description: CLI entry point for Embeddings Module.

www.jgoy.net
────────────────────────────────────
"""

import sys
import asyncio
import argparse
import json
from pathlib import Path

from personality.i18n import get_i18n

def cmd_info():
  """Show module information"""
  from memory.embeddings.module import EmbeddingsModule
  
  module = EmbeddingsModule.get_instance()
  info = module.get_info()
  
  print(json.dumps(info, indent=2, default=str))

async def cmd_health():
  """Run health checks"""
  from memory.embeddings.module import EmbeddingsModule
  from memory.embeddings.health import check_health

  module = EmbeddingsModule.get_instance()
  result = check_health(module)
  print(json.dumps(result, indent=2, default=str))

async def cmd_encode(text: str, model: str = None):
  """Generate embedding for a text"""
  from memory.embeddings.module import EmbeddingsModule
  from memory.embeddings.core.interfaces import EmbeddingRequest

  i18n = get_i18n()
  module = EmbeddingsModule.get_instance()

  if not module._initialized:
    print(i18n.t("embeddings.cli.initializing", "Initializing module..."))
    config = {}
    if model:
      config["model_name"] = model
    await module.initialize(config=config)
  
  request = EmbeddingRequest(text=text, model=model or "paraphrase-multilingual-MiniLM-L12-v2")
  response = await module.encode(request)
  
  print(json.dumps({
    "dimensions": response.dimensions,
    "model": response.model,
    "cache_hit": response.cache_hit,
    "latency_ms": response.latency_ms,
    "embedding": response.embedding[:5] + ["..."]
  }, indent=2))

async def cmd_chunk(file_path: str, doc_id: str = None):
  """Split document into chunks"""
  from memory.embeddings.module import EmbeddingsModule

  i18n = get_i18n()
  module = EmbeddingsModule.get_instance()

  if not module._initialized:
    print(i18n.t("embeddings.cli.initializing", "Initializing module..."))
    await module.initialize()

  file = Path(file_path)
  if not file.exists():
    print(i18n.t("embeddings.cli.file_not_found", "Error: File not found: {file_path}", file_path=file_path), file=sys.stderr)
    sys.exit(1)
  
  content = file.read_text(encoding="utf-8")
  doc_id = doc_id or file.stem
  
  result = await module.chunk_document(content, doc_id)
  
  print(json.dumps({
    "document_id": result.document_id,
    "chunk_count": result.chunk_count,
    "original_length": result.original_length,
    "chunks": [
      {
        "index": chunk.chunk_index,
        "section_title": chunk.section_title,
        "content_preview": chunk.content[:100] + "...",
        "char_range": f"{chunk.char_start}-{chunk.char_end}"
      }
      for chunk in result.chunks
    ]
  }, indent=2))

async def cmd_stats():
  """Show module statistics"""
  from memory.embeddings.module import EmbeddingsModule
  
  module = EmbeddingsModule.get_instance()
  
  if not module._initialized:
    print(get_i18n().t("embeddings.cli.not_initialized", "Module not initialized yet"))
    return
  
  stats = module.get_stats()
  
  print(json.dumps({
    "model_name": stats.model_name,
    "device": stats.device,
    "total_encodings": stats.total_encodings,
    "cache_hits": stats.cache_hits,
    "cache_misses": stats.cache_misses,
    "cache_hit_rate": f"{stats.cache_hit_rate:.1%}",
    "avg_latency_ms": f"{stats.avg_latency_ms:.2f}",
    "p90_latency_ms": f"{stats.p90_latency_ms:.2f}",
    "p99_latency_ms": f"{stats.p99_latency_ms:.2f}"
  }, indent=2))

def main():
  """Main CLI entry point"""
  i18n = get_i18n()
  parser = argparse.ArgumentParser(
    description=i18n.t("embeddings.cli.description", "Embeddings Module - Nexe 0.8"),
    formatter_class=argparse.RawDescriptionHelpFormatter,
    epilog=i18n.t(
      "embeddings.cli.epilog",
      "Examples:\n"
      " python3 -m memory.embeddings info\n"
      " python3 -m memory.embeddings health\n"
      " python3 -m memory.embeddings encode \"Hello world\"\n"
      " python3 -m memory.embeddings chunk document.txt\n"
      " python3 -m memory.embeddings stats"
    )
  )
  
  subparsers = parser.add_subparsers(
    dest="command",
    help=i18n.t("embeddings.cli.commands_help", "Available commands")
  )
  
  subparsers.add_parser(
    "info",
    help=i18n.t("embeddings.cli.info_help", "Show module information")
  )
  
  subparsers.add_parser(
    "health",
    help=i18n.t("embeddings.cli.health_help", "Run health checks")
  )
  
  encode_parser = subparsers.add_parser(
    "encode",
    help=i18n.t("embeddings.cli.encode_help", "Generate embedding for text")
  )
  encode_parser.add_argument(
    "text",
    help=i18n.t("embeddings.cli.encode_text_help", "Text to encode")
  )
  encode_parser.add_argument(
    "--model",
    help=i18n.t("embeddings.cli.encode_model_help", "Model to use (optional)")
  )
  
  chunk_parser = subparsers.add_parser(
    "chunk",
    help=i18n.t("embeddings.cli.chunk_help", "Split document into chunks")
  )
  chunk_parser.add_argument(
    "file",
    help=i18n.t("embeddings.cli.chunk_file_help", "Path to document file")
  )
  chunk_parser.add_argument(
    "--doc-id",
    help=i18n.t("embeddings.cli.chunk_doc_id_help", "Document ID (default: filename)")
  )
  
  subparsers.add_parser(
    "stats",
    help=i18n.t("embeddings.cli.stats_help", "Show module statistics")
  )
  
  args = parser.parse_args()
  
  if not args.command:
    parser.print_help()
    sys.exit(1)
  
  if args.command == "info":
    cmd_info()
  elif args.command == "health":
    asyncio.run(cmd_health())
  elif args.command == "encode":
    asyncio.run(cmd_encode(args.text, args.model))
  elif args.command == "chunk":
    asyncio.run(cmd_chunk(args.file, args.doc_id))
  elif args.command == "stats":
    asyncio.run(cmd_stats())
  else:
    parser.print_help()
    sys.exit(1)

if __name__ == "__main__":
  main()
