"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/module_registry.py
Description: Simple module registry for instances and capabilities.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ModuleRecord:
  """Registry entry for a loaded module."""
  name: str
  instance: Any
  module_id: Optional[str] = None
  capabilities: List[str] = field(default_factory=list)
  priority: int = 0


class ModuleRegistry:
  """
  Minimalist registry to access modules by name or capability.
  """

  def __init__(self) -> None:
    """Initialize an empty module registry."""
    self._modules: Dict[str, ModuleRecord] = {}

  def register(
    self,
    name: str,
    instance: Any,
    module_id: Optional[str] = None,
    capabilities: Optional[List[str]] = None,
    priority: int = 0,
  ) -> None:
    """Register a module instance under the given name.

    Args:
        name: Unique module name used as the lookup key.
        instance: The module instance to register.
        module_id: Optional identifier from the module manifest.
        capabilities: List of capability strings the module provides.
        priority: Higher values are returned first by :meth:`find_by_capability`.
    """
    caps = list(capabilities or [])
    self._modules[name] = ModuleRecord(
      name=name,
      instance=instance,
      module_id=module_id,
      capabilities=caps,
      priority=priority,
    )

  def get(self, name: str) -> Optional[ModuleRecord]:
    """Look up a registered module by name, or ``None`` if not found."""
    return self._modules.get(name)

  def list(self) -> List[ModuleRecord]:
    """Return all registered module records."""
    return list(self._modules.values())

  def find_by_capability(self, capability: str) -> List[ModuleRecord]:
    """Return modules that declare the given capability, sorted by priority descending."""
    matches = []
    for record in self._modules.values():
      if capability in record.capabilities:
        matches.append(record)
    matches.sort(key=lambda r: r.priority, reverse=True)
    return matches


__all__ = [
  "ModuleRegistry",
  "ModuleRecord",
]
