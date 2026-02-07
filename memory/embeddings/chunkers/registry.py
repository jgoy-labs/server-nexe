"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: memory/embeddings/chunkers/registry.py
Description: No description available.

www.jgoy.net
────────────────────────────────────
"""

import importlib
import inspect
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Type

from .base import BaseChunker
from personality.i18n.resolve import t_modular

logger = logging.getLogger(__name__)

def _t(key: str, fallback: str, **kwargs) -> str:
  return t_modular(f"embeddings.chunkers.{key}", fallback, **kwargs)

class ChunkerNotFoundError(Exception):
  """Chunker not found in the registry."""

  pass

class DuplicateChunkerError(Exception):
  """Chunker already registered."""

  pass

class ChunkerRegistry:
  """
  Central chunker registry with auto-discovery.

  INTEGRATION WITH MEMORY:
  - Memory will call get_chunker_for_format(extension) or get_chunker_for_type(content_type)
  - The registry returns the appropriate instance
  - Memory does not need to know specific chunkers

  Usage:
    registry = get_chunker_registry()
    chunker = registry.get_chunker_for_format('py')
    chunker = registry.get_chunker_for_format('txt')
    result = chunker.chunk(code_content)
  """

  def __init__(self) -> None:
    """Initialize an empty registry."""
    self._chunkers: Dict[str, Type[BaseChunker]] = {}
    self._instances: Dict[str, BaseChunker] = {}
    self._format_map: Dict[str, str] = {}
    self._type_map: Dict[str, str] = {}
    logger.debug(_t("registry_initialized", "ChunkerRegistry initialized"))

  def register(
    self, chunker_class: Type[BaseChunker]
  ) -> Type[BaseChunker]:
    """
    Register a chunker manually.

    Can also be used as a decorator:
      @registry.register
      class MyChunker(BaseChunker):
        ...

    Args:
      chunker_class: Class inheriting from BaseChunker

    Returns:
      The same class (to allow decorator usage)

    Raises:
      ValueError: If it does not inherit from BaseChunker
      DuplicateChunkerError: If a chunker with the same ID already exists
    """
    if not issubclass(chunker_class, BaseChunker):
      raise ValueError(
        _t(
          "invalid_chunker_class",
          "Expected BaseChunker subclass, got {chunker_class}",
          chunker_class=chunker_class,
        )
      )

    chunker_id = chunker_class.metadata["id"]

    if chunker_id in self._chunkers:
      raise DuplicateChunkerError(
        _t(
          "duplicate_chunker",
          "Chunker '{chunker_id}' already registered",
          chunker_id=chunker_id,
        )
      )

    self._chunkers[chunker_id] = chunker_class
    self._instances[chunker_id] = chunker_class()

    for fmt in chunker_class.metadata.get("formats", []):
      self._format_map[fmt.lower()] = chunker_id

    for ct in chunker_class.metadata.get("content_types", []):
      self._type_map[ct.lower()] = chunker_id

    logger.info(
      _t(
        "chunker_registered",
        "Registered chunker: {chunker_id} (formats: {formats})",
        chunker_id=chunker_id,
        formats=chunker_class.metadata.get("formats", []),
      )
    )

    return chunker_class

  def get_chunker(self, chunker_id: str) -> BaseChunker:
    """
    Get a chunker by ID.

    Args:
      chunker_id: Chunker ID ('chunker.text', 'chunker.code', etc.)

    Returns:
      Chunker instance

    Raises:
      ChunkerNotFoundError: If it does not exist
    """
    if chunker_id not in self._instances:
      raise ChunkerNotFoundError(
        _t(
          "chunker_not_found",
          "Chunker '{chunker_id}' not found. Available: {available}",
          chunker_id=chunker_id,
          available=list(self._chunkers.keys()),
        )
      )
    return self._instances[chunker_id]

  def get_chunker_for_format(self, file_extension: str) -> Optional[BaseChunker]:
    """
    Get the appropriate chunker for a file extension.

    MEMORY USES THIS METHOD to select a chunker.

    Args:
      file_extension: Extension without dot ('py', 'js', 'txt')

    Returns:
      BaseChunker or None if no match

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
    Get the appropriate chunker for a content type.

    Args:
      content_type: 'code', 'text', 'data'

    Returns:
      BaseChunker or None if no match
    """
    ct = content_type.lower()
    chunker_id = self._type_map.get(ct)

    if chunker_id:
      return self._instances[chunker_id]

    return None

  def get_default_chunker(self) -> BaseChunker:
    """
    Return the default chunker (text).

    MEMORY USES THIS METHOD if no specific match is found.

    Returns:
      TextChunker if it exists, or the first available chunker

    Raises:
      ChunkerNotFoundError: If no chunkers are registered
    """
    if "chunker.text" in self._instances:
      return self._instances["chunker.text"]

    if self._instances:
      return next(iter(self._instances.values()))

    raise ChunkerNotFoundError(
      _t("no_chunkers_registered", "No chunkers registered")
    )

  def auto_discover(self, chunkers_dir: Optional[Path] = None) -> int:
    """
    Auto-discover chunkers in a directory.

    Scans *_chunker.py files and registers BaseChunker classes.

    Args:
      chunkers_dir: Directory to scan (default: current directory)

    Returns:
      Number of discovered chunkers
    """
    if chunkers_dir is None:
      chunkers_dir = Path(__file__).parent

    if not chunkers_dir.exists():
      logger.warning(
        _t(
          "chunkers_dir_not_found",
          "Chunkers directory not found: {path}",
          path=chunkers_dir,
        )
      )
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
              logger.error(
                _t(
                  "register_failed",
                  "Failed to register {name}: {error}",
                  name=name,
                  error=str(e),
                )
              )

      except Exception as e:
        logger.error(
          _t(
            "import_failed",
            "Failed to import {path}: {error}",
            path=py_file,
            error=str(e),
          )
        )

    logger.info(
      _t(
        "auto_discovery_completed",
        "Auto-discovery completed: {count} chunkers found",
        count=discovered,
      )
    )
    return discovered

  def list_chunkers(self) -> List[Dict[str, Any]]:
    """
    List all registered chunkers with metadata.

    Returns:
      List of dictionaries with info for each chunker
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
    Registry statistics.

    Returns:
      Dict with total_chunkers, chunker_ids, supported_formats, etc.
    """
    return {
      "total_chunkers": len(self._chunkers),
      "chunker_ids": list(self._chunkers.keys()),
      "supported_formats": sorted(self._format_map.keys()),
      "supported_types": sorted(self._type_map.keys()),
    }

  def has_chunker(self, chunker_id: str) -> bool:
    """Check whether a chunker exists."""
    return chunker_id in self._chunkers

  def has_format_support(self, file_extension: str) -> bool:
    """Check whether an extension is supported."""
    ext = file_extension.lower().lstrip(".")
    return ext in self._format_map

  def __len__(self) -> int:
    """Return the number of registered chunkers."""
    return len(self._chunkers)

  def __repr__(self) -> str:
    return f"ChunkerRegistry(chunkers={len(self._chunkers)})"

_registry: Optional[ChunkerRegistry] = None

def get_chunker_registry() -> ChunkerRegistry:
  """
  Get the global chunker registry.

  MEMORY IMPORTS THIS FUNCTION.

  Creates the singleton if it does not exist and runs auto-discovery.

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
  Reset the registry (tests only).

  Remove the singleton to allow re-initialization.
  """
  global _registry
  _registry = None
