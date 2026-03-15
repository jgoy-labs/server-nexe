"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: memory/embeddings/chunkers/text_chunker.py
Description: No description available.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import re
import uuid
from typing import Any, Dict, List, Optional

from .base import BaseChunker, Chunk, ChunkingResult

class TextChunker(BaseChunker):
  """
  Smart chunker for narrative text.

  Ideal for:
  - Structured documents with sections (markdown, books)
  - Text with paragraphs
  - Content needing semantic context (section_title)

  Features:
  - Title detection (heuristic: short, uppercase, no dot)
  - Section title propagation: titles propagate to subsequent chunks
  - Dual strategy: by paragraphs (\\n\\n) or sentences (fallback)
  - Merge of small chunks

  Example:
    chunker = TextChunker(max_chunk_size=1000)
    result = chunker.chunk(text, document_id='doc123')
    for chunk in result.chunks:
      print(chunk.section_title, chunk.text[:50])
  """

  metadata: Dict[str, Any] = {
    "id": "chunker.text",
    "name": "Text Chunker",
    "description": "Smart chunking for narrative text with section detection",
    "category": "core",
    "version": "1.0.0",
    "formats": ["txt", "md", "rst", "rtf", "log", "text", "markdown"],
    "content_types": ["text", "markdown", "narrative", "document"],
  }

  default_config: Dict[str, Any] = {
    "max_chunk_size": 1500,
    "chunk_overlap": 200,
    "min_chunk_size": 100,
  }

  def chunk(
    self,
    text: str,
    document_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
  ) -> ChunkingResult:
    """
    Chunk narrative text with section detection.

    Args:
      text: Text to chunk
      document_id: Optional document ID
      metadata: Additional metadata

    Returns:
      ChunkingResult with chunks and propagated section_title
    """
    if not text or not text.strip():
      return ChunkingResult(
        document_id=document_id,
        chunks=[],
        total_chunks=0,
        original_length=0,
        chunker_id=self.metadata["id"],
      )

    doc_id = document_id or str(uuid.uuid4())
    original_length = len(text)
    meta = metadata or {}

    if "\n\n" in text:
      raw_chunks = self._chunk_by_paragraphs(text)
    else:
      raw_chunks = self._chunk_by_sentences(text)

    chunks: List[Chunk] = []
    current_section: Optional[str] = None
    char_pos = 0

    for chunk_text in raw_chunks:
      chunk_text = chunk_text.strip()
      if not chunk_text:
        continue

      if self._is_title(chunk_text):
        current_section = chunk_text
        continue

      start = text.find(chunk_text, char_pos)
      if start == -1:
        start = char_pos
      end = start + len(chunk_text)
      char_pos = end

      chunk = Chunk.create(
        text=chunk_text,
        start=start,
        end=end,
        index=len(chunks),
        document_id=doc_id,
        section_title=current_section,
        chunk_type="paragraph",
        metadata=meta.copy(),
      )
      chunks.append(chunk)

    chunks = self._merge_small_chunks(chunks)

    return ChunkingResult(
      document_id=doc_id,
      chunks=chunks,
      total_chunks=len(chunks),
      original_length=original_length,
      chunker_id=self.metadata["id"],
    )

  def supports(
    self, file_extension: Optional[str] = None, content_type: Optional[str] = None
  ) -> bool:
    """
    Indicates if format/type is supported.

    TextChunker is the default chunker, supports almost everything.
    """
    if file_extension:
      ext = file_extension.lower().lstrip(".")
      return ext in self.metadata["formats"]
    if content_type:
      return content_type.lower() in self.metadata["content_types"]
    return True

  def _chunk_by_paragraphs(self, text: str) -> List[str]:
    """
    Split by paragraphs (\\n\\n).

    If a paragraph is too long, fall back to sentences.
    """
    paragraphs = text.split("\n\n")
    result: List[str] = []

    for para in paragraphs:
      para = para.strip()
      if not para:
        continue

      if len(para) > self.config["max_chunk_size"]:
        result.extend(self._chunk_by_sentences(para))
      else:
        result.append(para)

    return result

  def _chunk_by_sentences(self, text: str) -> List[str]:
    """
    Split by sentences with overlap.

    Uses regex to detect sentence end (.!?).
    """
    sentences = re.split(r"(?<=[.!?])\s+", text)
    chunks: List[str] = []
    current = ""

    for sentence in sentences:
      sentence = sentence.strip()
      if not sentence:
        continue

      if len(current) + len(sentence) + 1 <= self.config["max_chunk_size"]:
        current += (" " if current else "") + sentence
      else:
        if current:
          chunks.append(current)
        current = sentence

    if current:
      chunks.append(current)

    return chunks

  def _is_title(self, text: str) -> bool:
    """
    Heuristic to detect if text is a title.

    A text is a title if:
    - It is short (<80 chars, <=10 words)
    - Starts with uppercase or number
    - Does not end with dot (except numbered lists like "1. Title")
    """
    text = text.strip()
    if not text:
      return False

    if len(text) > 80:
      return False

    word_count = len(text.split())
    if word_count > 10:
      return False

    if text.endswith(".") and not re.match(r"^\d+\.", text):
      return False

    if not (text[0].isupper() or text[0].isdigit()):
      return False

    if text.isupper():
      return True
    if text.startswith("#"):
      return True
    if re.match(r"^\d+\.\s+", text):
      return True

    return True

  def _merge_small_chunks(self, chunks: List[Chunk]) -> List[Chunk]:
    """
    Merges chunks that are too small with the next one.

    Chunks with less than min_chunk_size chars are merged.
    The resulting chunk type is 'merged'.
    """
    if not chunks:
      return chunks

    merged: List[Chunk] = []
    current: Optional[Chunk] = None

    for chunk in chunks:
      if current is None:
        current = chunk
      elif len(current.text) < self.config["min_chunk_size"]:
        merged_text = current.text + "\n\n" + chunk.text
        current = Chunk.create(
          text=merged_text,
          start=current.start_char,
          end=chunk.end_char,
          index=current.chunk_index,
          document_id=current.document_id,
          section_title=current.section_title or chunk.section_title,
          chunk_type="merged",
          metadata=current.metadata,
        )
      else:
        merged.append(current)
        current = chunk

    if current:
      merged.append(current)

    for idx, chunk in enumerate(merged):
      chunk.chunk_index = idx

    return merged