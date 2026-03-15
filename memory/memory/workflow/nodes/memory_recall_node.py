"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: memory/memory/workflow/nodes/memory_recall_node.py
Description: Node per recuperar memòries de Memory.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import logging
import os
import time
from typing import Dict, Any, List, Optional
from nexe_flow.core.node import Node, NodeMetadata, NodeInput, NodeOutput

from memory.memory import MemoryModule, MemoryType, MemoryEntry
from memory.memory.rag_logger import get_rag_logger

logger = logging.getLogger(__name__)

class MemoryRecallNode(Node):
  """
  Node per recuperar memòries de Memory.

  Fallback chain:
  1. FlashMemory (RAM) - més ràpid
  2. SQLite (persistence) - si RAM buida
  3. Qdrant (semantic search) - si query provided

  Exemple d'ús en workflow:
    ```yaml
    nodes:
     - id: recall_context
      type: memory.recall
      config:
       limit: 10
       entry_type: "episodic"
    ```
  """

  def get_metadata(self) -> NodeMetadata:
    """Metadata del node."""
    return NodeMetadata(
      id="memory.recall",
      name="Memory Recall",
      description="Recupera memòries (FlashMemory → SQLite → Qdrant)",
      category="nexe_native",
      version="1.1.0",
      inputs=[
        NodeInput(
          name="limit",
          type="number",
          required=False,
          description="Nombre màxim d'entrades",
          default=10
        ),
        NodeInput(
          name="entry_type",
          type="string",
          required=False,
          description="Tipus: episodic, semantic, o null per tots",
          default="episodic"
        ),
        NodeInput(
          name="query",
          type="string",
          required=False,
          description="Query per cerca semàntica a Qdrant",
          default=None
        ),
        NodeInput(
          name="person_id",
          type="string",
          required=False,
          description="ID de la persona",
          default="default"
        )
      ],
      outputs=[
        NodeOutput(name="context", type="string", description="Context per LLM"),
        NodeOutput(name="entries", type="array", description="Entrades trobades"),
        NodeOutput(name="entry_count", type="number", description="Nombre d'entrades"),
        NodeOutput(name="source", type="string", description="Font: flash/sqlite/qdrant")
      ]
    )

  async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
    """
    Executa el recall amb fallback chain.
    """
    start_time = time.time()
    limit = inputs.get("limit", 10)
    entry_type_str = inputs.get("entry_type", "episodic")
    query = inputs.get("query")
    person_id = inputs.get("person_id", "default")

    rag_log = get_rag_logger()
    rag_log.recall_start(query, limit, entry_type_str, person_id)

    logger.info("═" * 50)
    logger.info("MEMORY RECALL START")
    logger.info(f"  limit={limit}, type={entry_type_str}, query={query[:30] if query else 'None'}...")

    try:
      module = MemoryModule.get_instance()

      if not module._initialized:
        logger.info("  Auto-initializing MemoryModule...")
        await module.initialize()
        logger.info("  MemoryModule initialized")

      entries: List[MemoryEntry] = []
      source = "none"

      step_start = time.time()
      logger.info("  STEP 1: FlashMemory (RAM)")

      if module._flash_memory:
        flash_entries = await module._flash_memory.get_all(limit=limit)
        step_ms = (time.time() - step_start) * 1000
        logger.info(f"   FlashMemory entries: {len(flash_entries)}")

        rag_log.recall_step_flash(len(flash_entries), step_ms)

        if flash_entries:
          entries = flash_entries
          source = "flash"
          logger.info(f"  Found {len(entries)} in FlashMemory")
      else:
        rag_log.recall_step_flash(0, 0)
        logger.warning("   FlashMemory not available")

      if not entries and module._persistence:
        step_start = time.time()
        logger.info("  STEP 2: SQLite (fallback)")

        try:
          sqlite_entries = await module._persistence.get_recent(
            limit=limit,
            entry_types=[entry_type_str] if entry_type_str else None
          )
          step_ms = (time.time() - step_start) * 1000
          logger.info(f"   SQLite entries: {len(sqlite_entries)}")

          cached_count = 0
          if sqlite_entries:
            entries = sqlite_entries
            source = "sqlite"
            logger.info(f"  Found {len(entries)} in SQLite")

            if module._flash_memory:
              for entry in sqlite_entries:
                await module._flash_memory.store(entry)
              cached_count = len(sqlite_entries)
              logger.info(f"   Cached {len(sqlite_entries)} to FlashMemory")

          rag_log.recall_step_sqlite(len(sqlite_entries), step_ms, cached_count)
        except Exception as e:
          logger.warning(f"   SQLite error: {e}")
          rag_log.recall_step_sqlite(0, 0)

      if not entries and query and module._persistence:
        step_start = time.time()
        logger.info("  STEP 3: Qdrant (semantic search)")

        try:
          from memory.memory.pipeline.ingestion import IngestionPipeline

          embedding = await self._get_embedding(query)

          if embedding:
            logger.info(f"   Embedding generated: {len(embedding)} dims")

            qdrant_results = await module._persistence.search(
              query_vector=embedding,
              limit=limit
            )
            step_ms = (time.time() - step_start) * 1000
            logger.info(f"   Qdrant results: {len(qdrant_results)}")

            qdrant_dicts = []
            if qdrant_results:
              for entry_id, score in qdrant_results:
                entry = await module._persistence.get(str(entry_id))
                if entry:
                  entries.append(entry)
                  qdrant_dicts.append({
                    "id": entry_id,
                    "score": score,
                    "content": entry.content[:50] if entry else ""
                  })

              source = "qdrant"
              logger.info(f"  Found {len(entries)} via Qdrant")

            rag_log.recall_step_qdrant(len(entries), step_ms, qdrant_dicts)
          else:
            logger.warning("   Could not generate embedding")
            rag_log.recall_step_qdrant(0, 0)
        except Exception as e:
          logger.warning(f"   Qdrant error: {e}")
          rag_log.recall_step_qdrant(0, 0)

      context = self._format_context(entries)
      total_ms = (time.time() - start_time) * 1000

      logger.info("═" * 50)
      logger.info("MEMORY RECALL COMPLETE")
      logger.info(f"  Source: {source}")
      logger.info(f"  Entries: {len(entries)}")
      logger.info(f"  Context: {len(context)} chars")
      logger.info("═" * 50)

      rag_log.recall_complete(source, len(entries), len(context), total_ms)

      return {
        "context": context,
        "entries": [self._entry_to_dict(e) for e in entries],
        "entry_count": len(entries),
        "source": source
      }

    except Exception as e:
      logger.error(f"MEMORY RECALL ERROR: {e}", exc_info=True)
      rag_log.recall_error(str(e))
      return {
        "context": "",
        "entries": [],
        "entry_count": 0,
        "source": "error"
      }

  async def _get_embedding(self, text: str) -> Optional[List[float]]:
    """Genera embedding via Ollama API."""
    try:
      import httpx

      async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
          f"{os.environ.get('NEXE_OLLAMA_HOST', 'http://localhost:11434').rstrip('/')}/api/embeddings",
          json={"model": "nomic-embed-text", "prompt": text[:8000]}
        )

        if response.status_code == 200:
          data = response.json()
          return data.get("embedding")
    except Exception as e:
      logger.warning(f"Embedding error: {e}")

    return None

  def _format_context(self, entries: List[MemoryEntry]) -> str:
    """Formata entries com a context per LLM."""
    if not entries:
      return ""

    parts = ["[Memòries recents]"]
    for entry in entries[:10]:
      timestamp = entry.timestamp.strftime("%Y-%m-%d %H:%M") if entry.timestamp else "?"
      content = entry.content[:300] + "..." if len(entry.content) > 300 else entry.content
      parts.append(f"[{timestamp}] {content}")

    return "\n".join(parts)

  def _entry_to_dict(self, entry: MemoryEntry) -> Dict[str, Any]:
    """Converteix MemoryEntry a dict."""
    return {
      "id": entry.id,
      "content": entry.content[:200],
      "source": entry.source,
      "timestamp": entry.timestamp.isoformat() if entry.timestamp else None,
      "entry_type": entry.entry_type
    }

__all__ = ["MemoryRecallNode"]