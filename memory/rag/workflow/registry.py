"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: memory/rag/workflow/registry.py
Description: Auto-registre de nodes RAG al NodeRegistry global del Workflow Engine.

www.jgoy.net
────────────────────────────────────
"""

import structlog

from personality.i18n.resolve import t_modular

logger = structlog.get_logger(__name__)

def register_rag_nodes() -> None:
  """
  DEPRECATED: L'auto-discovery del WorkflowEngine registra automàticament
  els nodes RAG quan el mòdul s'inicialitza.

  Aquesta funció es manté per compatibilitat però ja no és necessària.
  Els nodes es descobreixen automàticament des de workflow/nodes/ perquè
  el manifest.toml té [module.integration] workflow_engine = true.

  Nodes auto-descoberts:
    - RAGSearchNode: Node de cerca al RAG amb generació de prompt
  """
  logger.info(
    "rag_nodes_auto_discovery_enabled",
    message=t_modular("rag.workflow.nodes_auto_discovery", "RAG nodes will be auto-discovered by WorkflowEngine"),
    nodes=["RAGSearchNode"]
  )

register_rag_nodes()
