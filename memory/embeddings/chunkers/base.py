"""
────────────────────────────────────
Server Nexe
Version: 0.8
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
  Chunk estàndard per Nexe - preparat per Memory.

  Attributes:
    chunk_id: ID únic del chunk (UUID)
    text: Contingut del chunk
    start_char: Posició inicial al document original
    end_char: Posició final al document original
    chunk_index: Índex del chunk (0, 1, 2...)
    document_id: ID del document pare (opcional)
    section_title: Títol de secció detectat (per TextChunker)
    chunk_type: Tipus de chunk ('paragraph', 'function', 'class', etc.)
    language: Llenguatge de programació (per CodeChunker)
    metadata: Metadata addicional (file_path, etc.)
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
    Factory method per crear un Chunk amb UUID automàtic.

    Args:
      text: Contingut del chunk
      start: Posició inicial
      end: Posició final
      index: Índex del chunk
      **kwargs: Altres atributs (document_id, section_title, etc.)

    Returns:
      Chunk amb chunk_id generat automàticament
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
    """Converteix el Chunk a diccionari."""
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
    """Retorna la longitud del text."""
    return len(self.text)

@dataclass
class ChunkingResult:
  """
  Resultat de chunking - interfície estàndard per Memory.

  Attributes:
    document_id: ID del document processat
    chunks: Llista de Chunks generats
    total_chunks: Nombre total de chunks
    original_length: Longitud del document original
    chunker_id: ID del chunker utilitzat
    created_at: Timestamp de creació
    metadata: Metadata addicional (language, etc.)
  """

  document_id: Optional[str]
  chunks: List[Chunk]
  total_chunks: int
  original_length: int
  chunker_id: str
  created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
  metadata: Dict[str, Any] = field(default_factory=dict)

  def to_dict(self) -> Dict[str, Any]:
    """Converteix el resultat a diccionari."""
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
  Classe base abstracta per tots els chunkers de Nexe.

  IMPORTANT per Memory:
  - Tots els chunkers hereten d'aquesta classe
  - ChunkerRegistry auto-descobreix subclasses
  - metadata.formats indica quins formats suporta

  Ús:
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
    Inicialitza el chunker amb configuració opcional.

    Args:
      **config: Paràmetres de configuració que sobreescriuen els defaults
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
    Mètode principal de chunking.

    MEMORY CRIDA AQUEST MÈTODE.

    Args:
      text: Contingut a chunkejar
      document_id: ID opcional del document
      metadata: Metadata addicional (file_path, language, etc.)

    Returns:
      ChunkingResult amb llista de Chunks
    """
    pass

  @abstractmethod
  def supports(
    self, file_extension: Optional[str] = None, content_type: Optional[str] = None
  ) -> bool:
    """
    Indica si aquest chunker suporta el format/tipus.

    MEMORY CRIDA AQUEST MÈTODE per seleccionar el chunker adequat.

    Args:
      file_extension: Extensió de fitxer ('py', 'txt', etc.)
      content_type: Tipus de contingut ('code', 'text', etc.)

    Returns:
      True si suporta, False altrament
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
    Estima el nombre de chunks sense processar.

    Útil per predir el cost de chunking.

    Args:
      text: Text a estimar

    Returns:
      Nombre estimat de chunks
    """
    if not text:
      return 0
    return max(1, len(text) // self.config["max_chunk_size"])

  def __repr__(self) -> str:
    return f"{self.__class__.__name__}(id={self.metadata['id']})"