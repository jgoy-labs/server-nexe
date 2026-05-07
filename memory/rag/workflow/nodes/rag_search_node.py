"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: memory/rag/workflow/nodes/rag_search_node.py
Description: Workflow Engine node to search documents in RAG.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from typing import Dict, Any, Optional
import structlog

from nexe_flow.core.node import Node, NodeMetadata, NodeInput, NodeOutput

from personality.i18n import get_i18n

logger = structlog.get_logger(__name__)

try:
  from memory.rag_sources.file import FileRAGSource  # type: ignore[attr-defined]  # FP: defensive import under try/except (FileRAGSource is a latent symbol, RAG_AVAILABLE manages its absence)
  RAG_AVAILABLE = True
except ImportError as e:
  RAG_AVAILABLE = False
  logger.warning(
    "rag_sources_not_available",
    error=str(e),
    message=get_i18n().t("rag.workflow.rag_not_available", "RAGSearchNode will not be registered. Install qdrant-client to enable RAG functionality.")
  )

class RAGSearchNode(Node):
  """
  Workflow node that searches documents in RAG and generates a prompt with context.

  Typical workflow:
    User Query → RAGSearchNode → Prompt with context → OllamaNode → Response

  Expected inputs:
    - query (str): User query

  Generated outputs:
    - prompt (str): Prompt generated with context
    - context (str): Concatenated text of found documents
    - results (List[Dict]): List of results with metadata
    - num_results (int): Number of results found

  Example configuration:
    {
      "source": "my-docs",
      "top_k": 5,
      "score_threshold": 0.7,
      "prompt_template": "Context:\\n{context}\\n\\nQuestion: {query}"
    }
  """

  def __init__(self) -> None:
    """Initialize the RAGSearch node."""
    super().__init__()

    self._rag_source: Optional[FileRAGSource] = None
    self.config: Dict[str, Any] = {}

    logger.info("rag_search_node_initialized")

  def get_metadata(self) -> NodeMetadata:
    """Return node metadata."""
    return NodeMetadata(
      id="rag.search",
      name="RAG Search",
      version="1.0.0",
      description="Cerca documents al RAG i genera prompt amb context",
      category="llm",
      inputs=[
        NodeInput(
          name="query",
          type="string",
          required=True,
          description="Query de l'usuari per cercar documents",
          json_schema={
            "type": "string",
            "minLength": 1,
            "description": "Text de la query"
          }
        )
      ],
      outputs=[
        NodeOutput(
          name="prompt",
          type="string",
          description="Prompt generat amb context dels documents trobats",
          json_schema={"type": "string"}
        ),
        NodeOutput(
          name="context",
          type="string",
          description="Text concatenat dels documents trobats",
          json_schema={"type": "string"}
        ),
        NodeOutput(
          name="results",
          type="array",
          description="Llista de resultats amb metadata",
          json_schema={"type": "array"}
        ),
        NodeOutput(
          name="num_results",
          type="number",
          description="Number of results found",
          json_schema={"type": "integer"}
        )
      ],
      icon="📚",
      color="#9b59b6",
      config_schema={
        "source": {
          "type": "string",
          "default": "my-docs",
          "description": "ID of the RAG source to use",
          "ui_widget": "text"
        },
        "top_k": {
          "type": "integer",
          "default": 5,
          "description": "Number of results to return",
          "ui_widget": "number"
        },
        "score_threshold": {
          "type": "number",
          "default": 0.7,
          "description": "Minimum similarity threshold (0.0-1.0)",
          "ui_widget": "number"
        },
        "prompt_template": {
          "type": "string",
          "default": "Context:\\n{context}\\n\\nQuestion: {query}",
          "description": "Prompt template with {context} and {query}",
          "ui_widget": "textarea"
        },
        "index_name": {
          "type": "string",
          "default": "documents",
          "description": "Qdrant/LanceDB index name",
          "ui_widget": "text"
        }
      }
    )

  def _init_rag_source(self):
    """
    Initialize the RAG source (lazy initialization).

    Returns:
      Initialized FileRAGSource

    Raises:
      RuntimeError: If the source cannot be initialized or RAG is not available
    """
    if not RAG_AVAILABLE:
      i18n = get_i18n()
      raise RuntimeError(
        i18n.t("rag.workflow.rag_functionality_not_available", "RAG functionality not available. Install qdrant-client: pip install qdrant-client")
      )

    if self._rag_source is None:
      try:
        source_id = self.config.get('source', 'my-docs')
        index_name = self.config.get('index_name', 'documents')

        self._rag_source = FileRAGSource(
          table_name=index_name
        )
        logger.info(
          "rag_source_initialized",
          source_id=source_id,
          index_name=index_name
        )
      except Exception as e:
        logger.error(
          "rag_source_init_failed",
          error=str(e)
        )
        i18n = get_i18n()
        raise RuntimeError(
          i18n.t("rag.workflow.failed_to_init_rag_source", "Failed to initialize RAG source: {error}", error=str(e))
        )

    return self._rag_source

  async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute the RAG search and generate the prompt with context.

    Args:
      inputs: Dictionary with:
        - query (str): User query

    Returns:
      Dictionary with:
        - prompt (str): Prompt generated with context
        - context (str): Concatenated text of documents
        - results (List[Dict]): Results with metadata
        - num_results (int): Number of results

    Raises:
      ValueError: If the 'query' parameter is missing
      RuntimeError: If the search fails
    """
    self.validate_inputs(inputs)

    query = inputs.get("query")
    if not query:
      i18n = get_i18n()
      raise ValueError(
        i18n.t("rag.workflow.missing_query", "Missing required input: 'query'")
      )

    top_k = self.config.get('top_k', 5)
    score_threshold = self.config.get('score_threshold', 0.7)
    prompt_template = self.config.get('prompt_template', "Context:\n{context}\n\nQuestion: {query}")

    logger.info(
      "rag_search_started",
      query=query[:100],
      top_k=top_k
    )

    try:
      rag_source = self._init_rag_source()

      from memory.rag_sources.base import SearchRequest

      request = SearchRequest(
        query=query,
        top_k=top_k
      )
      results = await rag_source.search(request)
      # Apply score threshold filtering
      results = [r for r in results if r.get("score", 1.0) >= score_threshold]

      context_chunks = []
      for i, result in enumerate(results, 1):
        text = result.get("text", "")
        score = result.get("score", 0.0)
        file_path = result.get("metadata", {}).get("file_path", "unknown")

        context_chunks.append(
          f"[{i}] (score: {score:.2f}, file: {file_path})\n{text}"
        )

      i18n = get_i18n()
      context = "\n\n".join(context_chunks) if context_chunks else i18n.t("rag.workflow.no_relevant_documents", "No relevant documents found.")

      prompt = prompt_template.format(
        context=context,
        query=query
      )

      logger.info(
        "rag_search_completed",
        num_results=len(results),
        context_length=len(context),
        prompt_length=len(prompt)
      )

      return {
        "prompt": prompt,
        "context": context,
        "results": results,
        "num_results": len(results)
      }

    except Exception as e:
      logger.error(
        "rag_search_failed",
        query=query[:100],
        error=str(e),
        exc_info=True
      )
      i18n = get_i18n()
      raise RuntimeError(
        i18n.t("rag.workflow.rag_search_failed", "RAG search failed: {error}", error=str(e))
      )

  def validate_config(self) -> bool:
    """
    Validate the node configuration.

    Returns:
      True if configuration is valid

    Raises:
      ValueError: If configuration is invalid
    """
    top_k = self.config.get('top_k', 5)
    score_threshold = self.config.get('score_threshold', 0.7)
    prompt_template = self.config.get('prompt_template', "Context:\n{context}\n\nQuestion: {query}")

    i18n = get_i18n()
    if top_k < 1:
      raise ValueError(
        i18n.t("rag.workflow.top_k_validation", "top_k must be >= 1")
      )

    if not 0.0 <= score_threshold <= 1.0:
      raise ValueError(
        i18n.t("rag.workflow.score_threshold_validation", "score_threshold must be between 0.0 and 1.0")
      )

    if "{context}" not in prompt_template:
      raise ValueError(
        i18n.t("rag.workflow.prompt_template_context_missing", "prompt_template must contain {context} placeholder")
      )

    if "{query}" not in prompt_template:
      raise ValueError(
        i18n.t("rag.workflow.prompt_template_query_missing", "prompt_template must contain {query} placeholder")
      )

    logger.debug("rag_search_node_config_valid")
    return True