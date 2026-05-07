"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: memory/rag/workflow/registry.py
Description: Auto-registration of RAG nodes to the global NodeRegistry of the Workflow Engine.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import structlog

from personality.i18n import get_i18n

logger = structlog.get_logger(__name__)

def register_rag_nodes() -> None:
  """
  DEPRECATED: WorkflowEngine auto-discovery automatically registers
  RAG nodes when the module initializes.

  This function is kept for compatibility but is no longer necessary.
  Nodes are auto-discovered from workflow/nodes/ because
  manifest.toml has [module.integration] workflow_engine = true.

  Auto-discovered nodes:
    - RAGSearchNode: RAG search node with prompt generation
  """
  i18n = get_i18n()
  logger.info(
    "rag_nodes_auto_discovery_enabled",
    message=i18n.t("rag.workflow.nodes_auto_discovery", "RAG nodes will be auto-discovered by WorkflowEngine"),
    nodes=["RAGSearchNode"]
  )

register_rag_nodes()