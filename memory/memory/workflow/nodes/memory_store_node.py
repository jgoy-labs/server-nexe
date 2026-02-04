"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: memory/memory/workflow/nodes/memory_store_node.py
Description: Node per emmagatzemar contingut a Memory (FlashMemory + Persistence).

www.jgoy.net
────────────────────────────────────
"""

import logging
from typing import Dict, Any
from nexe_flow.core.node import Node, NodeMetadata, NodeInput, NodeOutput

from memory.memory import MemoryModule, MemoryEntry, MemoryType

logger = logging.getLogger(__name__)

class MemoryStoreNode(Node):
  """
  Node per emmagatzemar contingut a Memory.

  Funcionalitats:
  - Crea MemoryEntry des del content
  - Ingereix via IngestionPipeline
  - Retorna entry_id per referència futura

  Exemple d'ús en workflow:
    ```yaml
    nodes:
     - id: store_conversation
      type: memory.store
      config:
       content: "{{ conversation_text }}"
       entry_type: "episodic"
       source: "chat"
       ttl_seconds: 3600
    ```
  """

  def get_metadata(self) -> NodeMetadata:
    """
    Metadata del node per al registre del Workflow Engine.

    Returns:
      NodeMetadata: Informació del node
    """
    return NodeMetadata(
      id="memory.store",
      name="Memory Store",
      description="Emmagatzema contingut a Memory (Flash + Persistence)",
      category="nexe_native",
      version="1.0.0",
      inputs=[
        NodeInput(
          name="content",
          type="string",
          required=True,
          description="Contingut a emmagatzemar"
        ),
        NodeInput(
          name="entry_type",
          type="string",
          required=False,
          description="Tipus: episodic o semantic",
          default="episodic"
        ),
        NodeInput(
          name="source",
          type="string",
          required=False,
          description="Font de la memòria",
          default="workflow"
        ),
        NodeInput(
          name="ttl_seconds",
          type="number",
          required=False,
          description="Time-to-live en segons (default: 1800)",
          default=1800
        )
      ],
      outputs=[
        NodeOutput(
          name="entry_id",
          type="string",
          description="ID de l'entrada emmagatzemada"
        ),
        NodeOutput(
          name="success",
          type="boolean",
          description="True si s'ha emmagatzemat correctament"
        )
      ]
    )

  async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
    """
    Executa el node: emmagatzema contingut a Memory.

    Args:
      inputs: Dict amb content, entry_type, source, ttl_seconds

    Returns:
      Dict amb entry_id i success
    """
    try:
      content = inputs.get("content")
      entry_type_str = inputs.get("entry_type", "episodic")
      source = inputs.get("source", "workflow")
      ttl_seconds = inputs.get("ttl_seconds", 1800)

      if not content or not content.strip():
        logger.warning("Empty content provided to memory.store")
        return {
          "entry_id": None,
          "success": False
        }

      try:
        entry_type = MemoryType(entry_type_str)
      except ValueError:
        logger.warning(f"Invalid entry_type: {entry_type_str}, using EPISODIC")
        entry_type = MemoryType.EPISODIC

      entry = MemoryEntry(
        entry_type=entry_type,
        content=content,
        source=source,
        ttl_seconds=ttl_seconds
      )

      module = MemoryModule.get_instance()

      if not module._initialized:
        logger.info("Auto-initializing MemoryModule for workflow")
        await module.initialize()

      if not module._pipeline:
        logger.error("IngestionPipeline not initialized after initialize()")
        return {
          "entry_id": None,
          "success": False
        }

      success = await module._pipeline.ingest(entry)

      logger.info(f"Memory stored: {entry.id} (success={success})")

      return {
        "entry_id": entry.id,
        "success": success
      }

    except Exception as e:
      logger.error(f"Error in memory.store: {e}", exc_info=True)
      return {
        "entry_id": None,
        "success": False
      }

__all__ = ["MemoryStoreNode"]