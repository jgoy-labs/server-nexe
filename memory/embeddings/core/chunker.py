"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: memory/embeddings/core/chunker.py
Description: SmartChunker: Intelligent chunking with section and title detection.

www.jgoy.net
────────────────────────────────────
"""

import re
import uuid
from typing import List, Optional
import structlog
from personality.i18n.resolve import t_modular

from memory.embeddings.core.interfaces import (
  ChunkMetadata,
  ChunkedDocument,
)

logger = structlog.get_logger()

def _t_log(key: str, fallback: str, **kwargs) -> str:
  return t_modular(f"embeddings.logs.{key}", fallback, **kwargs)

class SmartChunker:
  """
  Intelligent chunker with section detection.

  Features:
  - Title detection (heuristic: short, uppercase, no trailing dot)
  - Chunking by paragraphs (respects '\\n\\n')
  - Chunking by sentences (fallback)
  - Merge small chunks (<min_chunk_size)
  - Section title propagation (semantic context)

  Attributes:
    max_chunk_size: Max chars per chunk (default 1500)
    chunk_overlap: Overlap between chunks (200)
    min_chunk_size: Min chars per chunk (100)
  """

  def __init__(
    self,
    max_chunk_size: int = 1500,
    chunk_overlap: int = 200,
    min_chunk_size: int = 100
  ):
    """
    Init SmartChunker.

    Args:
      max_chunk_size: Max chars per chunk
      chunk_overlap: Overlap between consecutive chunks
      min_chunk_size: Min chars (smaller chunks are merged)
    """
    self.max_chunk_size = max_chunk_size
    self.chunk_overlap = chunk_overlap
    self.min_chunk_size = min_chunk_size

    logger.info(
      "smart_chunker_initialized",
      message=_t_log(
        "smart_chunker_initialized",
        "SmartChunker initialized (max_size={max_size}, overlap={overlap}, min_size={min_size})",
        max_size=max_chunk_size,
        overlap=chunk_overlap,
        min_size=min_chunk_size,
      ),
      max_size=max_chunk_size,
      overlap=chunk_overlap,
      min_size=min_chunk_size
    )

  def chunk_document(
    self,
    content: str,
    document_id: str
  ) -> ChunkedDocument:
    """
    Chunk document with section detection.

    Pipeline:
    1. Detect if it has paragraphs ('\\n\\n')
    2. Chunk by paragraphs or sentences
    3. Merge small chunks
    4. Enumerate chunks
    5. Return ChunkedDocument

    Args:
      content: Document text
      document_id: Unique document ID

    Returns:
      ChunkedDocument with chunk metadata
    """
    if not content.strip():
      return ChunkedDocument(
        document_id=document_id,
        original_length=0,
        chunks=[],
        chunk_count=0
      )

    if '\n\n' in content:
      chunks = self._chunk_by_paragraphs(content, document_id)
    else:
      chunks = self._chunk_by_sentences(content, document_id)

    chunks = self._merge_small_chunks(chunks)

    for i, chunk in enumerate(chunks):
      chunk.chunk_index = i

    logger.debug(
      "document_chunked",
      message=_t_log(
        "document_chunked",
        "Document chunked (document_id={document_id}, original_len={original_len}, chunk_count={chunk_count})",
        document_id=document_id,
        original_len=len(content),
        chunk_count=len(chunks),
      ),
      document_id=document_id,
      original_len=len(content),
      chunk_count=len(chunks)
    )

    return ChunkedDocument(
      document_id=document_id,
      original_length=len(content),
      chunks=chunks,
      chunk_count=len(chunks)
    )

  def _is_title(self, text: str) -> bool:
    """
    Detects if a text is a title.

    Criteria:
    - Short (<80 chars and <=10 words)
    - Starts with uppercase or number (numbered list)
    - Does not end with dot (or is numbered list)

    Args:
      text: Text to analyze

    Returns:
      True if is title
    """
    text = text.strip()

    if len(text) < 80 and len(text.split()) <= 10:
      if text:
        is_numbered_list = re.match(r'^\d+\.?\s+[A-Z]', text)
        starts_with_upper = text[0].isupper()

        if starts_with_upper or is_numbered_list:
          if not text.endswith('.') or is_numbered_list:
            return True

    return False

  def _chunk_by_paragraphs(
    self,
    content: str,
    document_id: str
  ) -> List[ChunkMetadata]:
    """
    Chunk by paragraphs (split '\\n\\n').

    Args:
      content: Document text
      document_id: Document ID

    Returns:
      List of ChunkMetadata
    """
    paragraphs = [p.strip() for p in content.split('\n\n') if p.strip()]
    chunks = []
    current_section = None
    char_pos = 0

    for para in paragraphs:
      if self._is_title(para):
        current_section = para
        char_pos += len(para) + 2
        continue

      if len(para) > self.max_chunk_size:
        sub_chunks = self._split_long_paragraph(para, char_pos, document_id, current_section)
        chunks.extend(sub_chunks)
        char_pos += len(para) + 2
      else:
        chunk = ChunkMetadata(
          chunk_id=str(uuid.uuid4()),
          document_id=document_id,
          chunk_index=len(chunks),
          char_start=char_pos,
          char_end=char_pos + len(para),
          section_title=current_section,
          chunk_type="paragraph"
        )
        chunks.append(chunk)
        char_pos += len(para) + 2

    return chunks

  def _split_long_paragraph(
    self,
    para: str,
    start_pos: int,
    document_id: str,
    section_title: Optional[str]
  ) -> List[ChunkMetadata]:
    """
    Split long paragraph by sentences.

    Args:
      para: Paragraph to split
      start_pos: Initial position in document
      document_id: Document ID
      section_title: Section title (if any)

    Returns:
      List of ChunkMetadata
    """
    sentences = re.split(r'(?<=[.!?])\s+', para)
    chunks = []
    current_chunk = ""
    chunk_start = start_pos

    for sentence in sentences:
      if len(current_chunk) + len(sentence) <= self.max_chunk_size:
        current_chunk += sentence + " "
      else:
        if current_chunk.strip():
          chunk = ChunkMetadata(
            chunk_id=str(uuid.uuid4()),
            document_id=document_id,
            chunk_index=0,
            char_start=chunk_start,
            char_end=chunk_start + len(current_chunk.strip()),
            section_title=section_title,
            chunk_type="paragraph"
          )
          chunks.append(chunk)
          chunk_start = chunk_start + len(current_chunk)

        current_chunk = sentence + " "

    if current_chunk.strip():
      chunk = ChunkMetadata(
        chunk_id=str(uuid.uuid4()),
        document_id=document_id,
        chunk_index=0,
        char_start=chunk_start,
        char_end=chunk_start + len(current_chunk.strip()),
        section_title=section_title,
        chunk_type="paragraph"
      )
      chunks.append(chunk)

    return chunks

  def _chunk_by_sentences(
    self,
    content: str,
    document_id: str
  ) -> List[ChunkMetadata]:
    """
    Chunk by sentences (fallback if no paragraphs).

    Args:
      content: Document text
      document_id: Document ID

    Returns:
      List of ChunkMetadata
    """
    sentences = re.split(r'(?<=[.!?])\s+', content)
    chunks = []
    current_chunk = ""
    chunk_start = 0

    for sentence in sentences:
      if len(current_chunk) + len(sentence) <= self.max_chunk_size:
        current_chunk += sentence + " "
      else:
        if current_chunk.strip():
          chunk = ChunkMetadata(
            chunk_id=str(uuid.uuid4()),
            document_id=document_id,
            chunk_index=len(chunks),
            char_start=chunk_start,
            char_end=chunk_start + len(current_chunk.strip()),
            section_title=None,
            chunk_type="paragraph"
          )
          chunks.append(chunk)
          chunk_start += len(current_chunk)

        current_chunk = sentence + " "

    if current_chunk.strip():
      chunk = ChunkMetadata(
        chunk_id=str(uuid.uuid4()),
        document_id=document_id,
        chunk_index=len(chunks),
        char_start=chunk_start,
        char_end=chunk_start + len(current_chunk.strip()),
        section_title=None,
        chunk_type="paragraph"
      )
      chunks.append(chunk)

    return chunks

  def _merge_small_chunks(
    self,
    chunks: List[ChunkMetadata]
  ) -> List[ChunkMetadata]:
    """
    Merge small chunks (<min_chunk_size) with adjacent chunks.

    Args:
      chunks: List of chunks

    Returns:
      List of merged chunks
    """
    if not chunks:
      return []

    merged = []
    i = 0

    while i < len(chunks):
      current = chunks[i]
      chunk_size = current.char_end - current.char_start

      if chunk_size < self.min_chunk_size and i < len(chunks) - 1:
        next_chunk = chunks[i + 1]

        current.char_end = next_chunk.char_end
        current.chunk_type = "merged"
        i += 1

      merged.append(current)
      i += 1

    return merged
