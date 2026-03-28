"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: memory/embeddings/workflow/nodes/chunking_node.py
Description: Workflow node per chunking de documents.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from typing import Any, Dict, Optional

from memory.embeddings.chunkers import get_chunker_registry
from memory.embeddings.core.chunker import SmartChunker

async def chunking_node(
  content: str,
  document_id: str,
  max_chunk_size: int = 1500,
  chunk_overlap: int = 200,
  min_chunk_size: int = 100,
  file_path: Optional[str] = None,
  content_type: Optional[str] = None,
  use_registry: bool = True,
) -> Dict[str, Any]:
  """
  Workflow node: Chunk document amb selecció automàtica de chunker.

  Selecció automàtica de chunker:
  - Si file_path té extensió .py/.js/.ts → CodeChunker (NO overlap)
  - Si file_path té extensió .txt/.md → TextChunker
  - Sense file_path → SmartChunker (comportament legacy)

  Args:
    content: Text del document
    document_id: ID únic del document
    max_chunk_size: Màxim chars per chunk
    chunk_overlap: Overlap entre chunks
    min_chunk_size: Mínim chars per chunk
    file_path: Ruta del fitxer (per seleccionar chunker)
    content_type: Tipus de contingut ('code', 'text', etc.)
    use_registry: Si True, usa ChunkerRegistry (default True)

  Returns:
    Dict amb:
    - document_id: str
    - chunk_count: int
    - chunks: List[Dict] amb metadata
    - original_length: int
    - chunker_id: str (ID del chunker usat)
  """
  if use_registry and (file_path or content_type):
    return await _chunk_with_registry(
      content=content,
      document_id=document_id,
      file_path=file_path,
      content_type=content_type,
      max_chunk_size=max_chunk_size,
      chunk_overlap=chunk_overlap,
      min_chunk_size=min_chunk_size,
    )
  else:
    return await _chunk_with_smart_chunker(
      content=content,
      document_id=document_id,
      max_chunk_size=max_chunk_size,
      chunk_overlap=chunk_overlap,
      min_chunk_size=min_chunk_size,
    )

async def _chunk_with_registry(
  content: str,
  document_id: str,
  file_path: Optional[str],
  content_type: Optional[str],
  max_chunk_size: int,
  chunk_overlap: int,
  min_chunk_size: int,
) -> Dict[str, Any]:
  """
  Chunk usant ChunkerRegistry per selecció automàtica.

  MEMORY USA AQUEST PATRÓ per processar documents.
  """
  registry = get_chunker_registry()

  chunker = None

  if file_path:
    ext = file_path.rsplit(".", 1)[-1] if "." in file_path else ""
    if ext:
      chunker = registry.get_chunker_for_format(ext)

  if chunker is None and content_type:
    chunker = registry.get_chunker_for_type(content_type)

  if chunker is None:
    chunker = registry.get_default_chunker()

  chunker.set_config(
    max_chunk_size=max_chunk_size,
    chunk_overlap=chunk_overlap,
    min_chunk_size=min_chunk_size,
  )

  metadata = {}
  if file_path:
    metadata["file_path"] = file_path
  if content_type:
    metadata["content_type"] = content_type

  result = chunker.chunk(
    text=content,
    document_id=document_id,
    metadata=metadata,
  )

  chunks_data = [
    {
      "chunk_id": chunk.chunk_id,
      "chunk_index": chunk.chunk_index,
      "char_start": chunk.start_char,
      "char_end": chunk.end_char,
      "text": chunk.text,
      "section_title": chunk.section_title,
      "chunk_type": chunk.chunk_type,
      "language": chunk.language,
      "metadata": chunk.metadata,
    }
    for chunk in result.chunks
  ]

  return {
    "document_id": result.document_id,
    "chunk_count": result.total_chunks,
    "chunks": chunks_data,
    "original_length": result.original_length,
    "created_at": result.created_at,
    "chunker_id": result.chunker_id,
  }

async def _chunk_with_smart_chunker(
  content: str,
  document_id: str,
  max_chunk_size: int,
  chunk_overlap: int,
  min_chunk_size: int,
) -> Dict[str, Any]:
  """
  Chunk amb SmartChunker (comportament legacy).

  Mantingut per retrocompatibilitat.
  """
  chunker = SmartChunker(
    max_chunk_size=max_chunk_size,
    chunk_overlap=chunk_overlap,
    min_chunk_size=min_chunk_size,
  )

  chunked_doc = chunker.chunk_document(content, document_id)

  chunks_data = [
    {
      "chunk_id": chunk.chunk_id,
      "chunk_index": chunk.chunk_index,
      "char_start": chunk.char_start,
      "char_end": chunk.char_end,
      "section_title": chunk.section_title,
      "chunk_type": chunk.chunk_type,
      "token_count": chunk.token_count,
    }
    for chunk in chunked_doc.chunks
  ]

  return {
    "document_id": chunked_doc.document_id,
    "chunk_count": chunked_doc.chunk_count,
    "chunks": chunks_data,
    "original_length": chunked_doc.original_length,
    "created_at": chunked_doc.created_at.isoformat(),
    "chunker_id": "legacy.smart_chunker",
  }