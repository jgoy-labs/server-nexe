"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: memory/memory/workflow/nodes/memory_store_node.py
Description: Node to store content in Memory (FlashMemory + Persistence).

www.jgoy.net
────────────────────────────────────
"""

import logging
from typing import Dict, Any
from nexe_flow.core.node import Node, NodeMetadata, NodeInput, NodeOutput

from memory.memory import MemoryModule, MemoryEntry, MemoryType
from personality.i18n.resolve import t_modular

logger = logging.getLogger(__name__)

def _t_log(key: str, fallback: str, **kwargs) -> str:
  return t_modular(f"memory.workflow.store.logs.{key}", fallback, **kwargs)

class MemoryStoreNode(Node):
  """
  Node to store content in Memory.

  Capabilities:
  - Create MemoryEntry from content
  - Ingest via IngestionPipeline
  - Return entry_id for future reference

  Example usage in a workflow:
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
    Node metadata for Workflow Engine registration.

    Returns:
      NodeMetadata: Node information
    """
    return NodeMetadata(
      id="memory.store",
      name="Memory Store",
      description=t_modular(
        "memory.workflow.store.description",
        "Store content in Memory (Flash + Persistence)"
      ),
      category="nexe_native",
      version="1.0.0",
      inputs=[
        NodeInput(
          name="content",
          type="string",
          required=True,
          description=t_modular(
            "memory.workflow.store.input_content",
            "Content to store"
          )
        ),
        NodeInput(
          name="entry_type",
          type="string",
          required=False,
          description=t_modular(
            "memory.workflow.store.input_entry_type",
            "Type: episodic or semantic"
          ),
          default="episodic"
        ),
        NodeInput(
          name="source",
          type="string",
          required=False,
          description=t_modular(
            "memory.workflow.store.input_source",
            "Memory source"
          ),
          default="workflow"
        ),
        NodeInput(
          name="ttl_seconds",
          type="number",
          required=False,
          description=t_modular(
            "memory.workflow.store.input_ttl",
            "Time-to-live in seconds (default: 1800)"
          ),
          default=1800
        )
      ],
      outputs=[
        NodeOutput(
          name="entry_id",
          type="string",
          description=t_modular(
            "memory.workflow.store.output_entry_id",
            "Stored entry ID"
          )
        ),
        NodeOutput(
          name="success",
          type="boolean",
          description=t_modular(
            "memory.workflow.store.output_success",
            "True if stored successfully"
          )
        )
      ]
    )

  async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute the node: store content in Memory.

    Args:
      inputs: Dict with content, entry_type, source, ttl_seconds

    Returns:
      Dict with entry_id and success
    """
    try:
      content = inputs.get("content")
      entry_type_str = inputs.get("entry_type", "episodic")
      source = inputs.get("source", "workflow")
      ttl_seconds = inputs.get("ttl_seconds", 1800)

      if not content or not content.strip():
        logger.warning(_t_log("empty_content", "Empty content provided to memory.store"))
        return {
          "entry_id": None,
          "success": False
        }

      try:
        entry_type = MemoryType(entry_type_str)
      except ValueError:
        logger.warning(
          _t_log(
            "invalid_entry_type",
            "Invalid entry_type: {entry_type}, using EPISODIC",
            entry_type=entry_type_str,
          )
        )
        entry_type = MemoryType.EPISODIC

      entry = MemoryEntry(
        entry_type=entry_type,
        content=content,
        source=source,
        ttl_seconds=ttl_seconds
      )

      module = MemoryModule.get_instance()

      if not module._initialized:
        logger.info(_t_log("auto_init", "Auto-initializing MemoryModule for workflow"))
        await module.initialize()

      if not module._pipeline:
        logger.error(
          _t_log(
            "pipeline_not_initialized",
            "IngestionPipeline not initialized after initialize()"
          )
        )
        return {
          "entry_id": None,
          "success": False
        }

      success = await module._pipeline.ingest(entry)

      logger.info(
        _t_log(
          "stored",
          "Memory stored: {entry_id} (success={success})",
          entry_id=entry.id,
          success=success,
        )
      )

      return {
        "entry_id": entry.id,
        "success": success
      }

    except Exception as e:
      logger.error(
        _t_log("store_error", "Error in memory.store: {error}", error=str(e)),
        exc_info=True
      )
      return {
        "entry_id": None,
        "success": False
      }

__all__ = ["MemoryStoreNode"]
