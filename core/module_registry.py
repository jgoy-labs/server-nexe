"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy
Location: core/module_registry.py
Description: Simple module registry by instance and capabilities.

www.jgoy.net
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
  Minimal registry to access modules by name or capability.
  """

  def __init__(self) -> None:
    self._modules: Dict[str, ModuleRecord] = {}

  def register(
    self,
    name: str,
    instance: Any,
    module_id: Optional[str] = None,
    capabilities: Optional[List[str]] = None,
    priority: int = 0,
  ) -> None:
    caps = list(capabilities or [])
    self._modules[name] = ModuleRecord(
      name=name,
      instance=instance,
      module_id=module_id,
      capabilities=caps,
      priority=priority,
    )

  def get(self, name: str) -> Optional[ModuleRecord]:
    return self._modules.get(name)

  def list(self) -> List[ModuleRecord]:
    return list(self._modules.values())

  def find_by_capability(self, capability: str) -> List[ModuleRecord]:
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
