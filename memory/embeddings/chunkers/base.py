"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: memory/embeddings/chunkers/base.py
Description: No description available.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import uuid

@dataclass
class Chunk:
  """
  Standard chunk for Nexe - prepared for Memory.

  Attributes:
    chunk_id: Unique chunk ID (UUID)
    text: Chunk content
    start_char: Start position in the original document
    end_char: End position in the original document
    chunk_index: Chunk index (0, 1, 2...)
    document_id: Parent document ID (optional)
    section_title: Detected section title (for TextChunker)
    chunk_type: Chunk type ('paragraph', 'function', 'class', etc.)
    language: Programming language (for CodeChunker)
    metadata: Additional metadata (file_path, etc.)
  """

  chunk_id: str
  text: str
  start_char: int
  end_char: int
  chunk_index: int
  document_id: Optional[str] = None
  section_title: Optional[str] = None
  chunk_type: str = "text"
  language: Optional[str] = None
  metadata: Dict[str, Any] = field(default_factory=dict)

  @classmethod
  def create(
    cls,
    text: str,
    start: int,
    end: int,
    index: int,
    **kwargs: Any,
  ) -> "Chunk":
    """
    Factory method to create a Chunk with automatic UUID.

    Args:
      text: Chunk content
      start: Start position
      end: End position
      index: Chunk index
      **kwargs: Other attributes (document_id, section_title, etc.)

    Returns:
      Chunk with automatically generated chunk_id
    """
    return cls(
      chunk_id=str(uuid.uuid4()),
      text=text,
      start_char=start,
      end_char=end,
      chunk_index=index,
      **kwargs,
    )

  def to_dict(self) -> Dict[str, Any]:
    """Converts the Chunk to a dictionary."""
    return {
      "chunk_id": self.chunk_id,
      "text": self.text,
      "start_char": self.start_char,
      "end_char": self.end_char,
      "chunk_index": self.chunk_index,
      "document_id": self.document_id,
      "section_title": self.section_title,
      "chunk_type": self.chunk_type,
      "language": self.language,
      "metadata": self.metadata,
    }

  def __len__(self) -> int:
    """Returns the length of the text."""
    return len(self.text)

@dataclass
class ChunkingResult:
  """
  Chunking result - standard interface for Memory.

  Attributes:
    document_id: ID of the processed document
    chunks: List of generated Chunks
    total_chunks: Total number of chunks
    original_length: Length of the original document
    chunker_id: ID of the chunker used
    created_at: Creation timestamp
    metadata: Additional metadata (language, etc.)
  """

  document_id: Optional[str]
  chunks: List[Chunk]
  total_chunks: int
  original_length: int
  chunker_id: str
  created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
  metadata: Dict[str, Any] = field(default_factory=dict)

  def to_dict(self) -> Dict[str, Any]:
    """Converts the result to a dictionary."""
    return {
      "document_id": self.document_id,
      "chunks": [c.to_dict() for c in self.chunks],
      "total_chunks": self.total_chunks,
      "original_length": self.original_length,
      "chunker_id": self.chunker_id,
      "created_at": self.created_at,
      "metadata": self.metadata,
    }

  def get_texts(self) -> List[str]:
    """Return only the text content of the chunks."""
    return [c.text for c in self.chunks]

class BaseChunker(ABC):
  """
  Abstract base class for all Nexe chunkers.

  IMPORTANT for Memory:
  - All chunkers inherit from this class
  - ChunkerRegistry auto-discovers subclasses
  - metadata.formats indicates which formats are supported

  Usage:
    class MyChunker(BaseChunker):
      metadata = {
        'id': 'chunker.my',
        'name': 'My Chunker',
        'formats': ['xyz'],
        'content_types': ['custom'],
      }

      def chunk(self, text, document_id=None, metadata=None):
        pass

      def supports(self, file_extension=None, content_type=None):
        return file_extension in self.metadata['formats']
  """

  metadata: Dict[str, Any] = {
    "id": "base.chunker",
    "name": "Base Chunker",
    "description": "Abstract base class for all chunkers",
    "category": "core",
    "version": "1.0.0",
    "formats": [],
    "content_types": [],
  }

  default_config: Dict[str, Any] = {
    "max_chunk_size": 1500,
    "chunk_overlap": 200,
    "min_chunk_size": 100,
  }

  def __init__(self, **config: Any) -> None:
    """
    Initializes the chunker with optional configuration.

    Args:
      **config: Configuration parameters that override the defaults
    """
    self.config = {**self.default_config, **config}

  @abstractmethod
  def chunk(
    self,
    text: str,
    document_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
  ) -> ChunkingResult:
    """
    Main chunking method.

    MEMORY CALLS THIS METHOD.

    Args:
      text: Content to chunk
      document_id: Optional document ID
      metadata: Additional metadata (file_path, language, etc.)

    Returns:
      ChunkingResult with list of Chunks
    """
    pass

  @abstractmethod
  def supports(
    self, file_extension: Optional[str] = None, content_type: Optional[str] = None
  ) -> bool:
    """
    Indicates whether this chunker supports the format/type.

    MEMORY CALLS THIS METHOD to select the appropriate chunker.

    Args:
      file_extension: File extension ('py', 'txt', etc.)
      content_type: Content type ('code', 'text', etc.)

    Returns:
      True if supported, False otherwise
    """
    pass

  def get_config(self) -> Dict[str, Any]:
    """Return the current configuration."""
    return self.config.copy()

  def set_config(self, **config: Any) -> None:
    """Update configuration values."""
    for key, value in config.items():
      if key in self.config:
        self.config[key] = value

  def estimate_chunks(self, text: str) -> int:
    """
    Estimates the number of chunks without processing.

    Useful for predicting the cost of chunking.

    Args:
      text: Text to estimate

    Returns:
      Estimated number of chunks
    """
    if not text:
      return 0
    return max(1, len(text) // self.config["max_chunk_size"])

  def __repr__(self) -> str:
    return f"{self.__class__.__name__}(id={self.metadata['id']})"