"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: memory/embeddings/chunkers/registry.py
Description: No description available.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import importlib
import inspect
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Type

from .base import BaseChunker

logger = logging.getLogger(__name__)

class ChunkerNotFoundError(Exception):
  """Chunker no trobat al registry."""

  pass

class DuplicateChunkerError(Exception):
  """Chunker ja registrat."""

  pass

class ChunkerRegistry:
  """
  Registry central de chunkers amb auto-discovery.

  INTEGRACIÓ AMB MEMORY:
  - Memory cridarà get_chunker_for_format(extension) o get_chunker_for_type(content_type)
  - El registry retorna la instància adequada
  - Memory no necessita conèixer els chunkers específics

  Ús:
    registry = get_chunker_registry()
    chunker = registry.get_chunker_for_format('py')
    chunker = registry.get_chunker_for_format('txt')
    result = chunker.chunk(code_content)
  """

  def __init__(self) -> None:
    """Inicialitza el registry buit."""
    self._chunkers: Dict[str, Type[BaseChunker]] = {}
    self._instances: Dict[str, BaseChunker] = {}
    self._format_map: Dict[str, str] = {}
    self._type_map: Dict[str, str] = {}
    logger.debug("ChunkerRegistry initialized")

  def register(
    self, chunker_class: Type[BaseChunker]
  ) -> Type[BaseChunker]:
    """
    Registra un chunker manualment.

    També es pot usar com a decorador:
      @registry.register
      class MyChunker(BaseChunker):
        ...

    Args:
      chunker_class: Classe que hereta de BaseChunker

    Returns:
      La mateixa classe (per permetre ús com a decorador)

    Raises:
      ValueError: Si no hereta de BaseChunker
      DuplicateChunkerError: Si ja existeix un chunker amb el mateix ID
    """
    if not issubclass(chunker_class, BaseChunker):
      raise ValueError(f"Expected BaseChunker subclass, got {chunker_class}")

    chunker_id = chunker_class.metadata["id"]

    if chunker_id in self._chunkers:
      raise DuplicateChunkerError(f"Chunker '{chunker_id}' already registered")

    self._chunkers[chunker_id] = chunker_class
    self._instances[chunker_id] = chunker_class()

    for fmt in chunker_class.metadata.get("formats", []):
      self._format_map[fmt.lower()] = chunker_id

    for ct in chunker_class.metadata.get("content_types", []):
      self._type_map[ct.lower()] = chunker_id

    logger.info(
      f"Registered chunker: {chunker_id} "
      f"(formats: {chunker_class.metadata.get('formats', [])})"
    )

    return chunker_class

  def get_chunker(self, chunker_id: str) -> BaseChunker:
    """
    Obté un chunker per ID.

    Args:
      chunker_id: ID del chunker ('chunker.text', 'chunker.code', etc.)

    Returns:
      Instància del chunker

    Raises:
      ChunkerNotFoundError: Si no existeix
    """
    if chunker_id not in self._instances:
      raise ChunkerNotFoundError(
        f"Chunker '{chunker_id}' not found. "
        f"Available: {list(self._chunkers.keys())}"
      )
    return self._instances[chunker_id]

  def get_chunker_for_format(self, file_extension: str) -> Optional[BaseChunker]:
    """
    Obté el chunker adequat per una extensió de fitxer.

    MEMORY USA AQUEST MÈTODE per seleccionar chunker.

    Args:
      file_extension: Extensió sense punt ('py', 'js', 'txt')

    Returns:
      BaseChunker o None si no hi ha match

    Example:
      chunker = registry.get_chunker_for_format('py')
      chunker = registry.get_chunker_for_format('txt')
    """
    ext = file_extension.lower().lstrip(".")
    chunker_id = self._format_map.get(ext)

    if chunker_id:
      return self._instances[chunker_id]

    for chunker in self._instances.values():
      if chunker.supports(file_extension=ext):
        return chunker

    return None

  def get_chunker_for_type(self, content_type: str) -> Optional[BaseChunker]:
    """
    Obté el chunker adequat per un tipus de contingut.

    Args:
      content_type: 'code', 'text', 'data'

    Returns:
      BaseChunker o None si no hi ha match
    """
    ct = content_type.lower()
    chunker_id = self._type_map.get(ct)

    if chunker_id:
      return self._instances[chunker_id]

    return None

  def get_default_chunker(self) -> BaseChunker:
    """
    Retorna el chunker per defecte (text).

    MEMORY USA AQUEST MÈTODE si no troba match específic.

    Returns:
      TextChunker si existeix, o el primer chunker disponible

    Raises:
      ChunkerNotFoundError: Si no hi ha chunkers registrats
    """
    if "chunker.text" in self._instances:
      return self._instances["chunker.text"]

    if self._instances:
      return next(iter(self._instances.values()))

    raise ChunkerNotFoundError("No chunkers registered")

  def auto_discover(self, chunkers_dir: Optional[Path] = None) -> int:
    """
    Auto-descobreix chunkers d'un directori.

    Escaneja fitxers *_chunker.py i registra classes BaseChunker.

    Args:
      chunkers_dir: Directori a escanejar (default: directori actual)

    Returns:
      Nombre de chunkers descoberts
    """
    if chunkers_dir is None:
      chunkers_dir = Path(__file__).parent

    if not chunkers_dir.exists():
      logger.warning(f"Chunkers directory not found: {chunkers_dir}")
      return 0

    discovered = 0

    for py_file in chunkers_dir.glob("*_chunker.py"):
      if py_file.name.startswith("_") or py_file.name.startswith("test_"):
        continue

      try:
        module_name = py_file.stem
        module = importlib.import_module(f".{module_name}", package=__package__)

        for name, obj in inspect.getmembers(module, inspect.isclass):
          if (
            issubclass(obj, BaseChunker)
            and obj is not BaseChunker
            and obj.metadata["id"] not in self._chunkers
          ):
            try:
              self.register(obj)
              discovered += 1
            except Exception as e:
              logger.error(f"Failed to register {name}: {e}")

      except Exception as e:
        logger.error(f"Failed to import {py_file}: {e}")

    logger.info(f"Auto-discovery completed: {discovered} chunkers found")
    return discovered

  def list_chunkers(self) -> List[Dict[str, Any]]:
    """
    Llista tots els chunkers registrats amb metadata.

    Returns:
      Llista de diccionaris amb info de cada chunker
    """
    return [
      {
        "id": c.metadata["id"],
        "name": c.metadata["name"],
        "description": c.metadata.get("description", ""),
        "formats": c.metadata.get("formats", []),
        "content_types": c.metadata.get("content_types", []),
        "category": c.metadata.get("category", ""),
      }
      for c in self._instances.values()
    ]

  def get_stats(self) -> Dict[str, Any]:
    """
    Estadístiques del registry.

    Returns:
      Dict amb total_chunkers, chunker_ids, supported_formats, etc.
    """
    return {
      "total_chunkers": len(self._chunkers),
      "chunker_ids": list(self._chunkers.keys()),
      "supported_formats": sorted(self._format_map.keys()),
      "supported_types": sorted(self._type_map.keys()),
    }

  def has_chunker(self, chunker_id: str) -> bool:
    """Comprova si existeix un chunker."""
    return chunker_id in self._chunkers

  def has_format_support(self, file_extension: str) -> bool:
    """Check if a file extension is supported."""
    ext = file_extension.lower().lstrip(".")
    return ext in self._format_map

  def __len__(self) -> int:
    """Retorna el nombre de chunkers registrats."""
    return len(self._chunkers)

  def __repr__(self) -> str:
    return f"ChunkerRegistry(chunkers={len(self._chunkers)})"

_registry: Optional[ChunkerRegistry] = None

def get_chunker_registry() -> ChunkerRegistry:
  """
  Obté el registry global de chunkers.

  MEMORY IMPORTA AQUESTA FUNCIÓ.

  Crea el singleton si no existeix i fa auto-discovery.

  Returns:
    ChunkerRegistry singleton

  Example:
    from memory.embeddings.chunkers import get_chunker_registry

    registry = get_chunker_registry()
    chunker = registry.get_chunker_for_format('py')
  """
  global _registry
  if _registry is None:
    _registry = ChunkerRegistry()
    _registry.auto_discover()
  return _registry

def reset_registry() -> None:
  """
  Reset del registry (només per tests).

  Elimina el singleton per permetre re-inicialització.
  """
  global _registry
  _registry = None