"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: personality/module_manager/core_modules.py
Description: Defines the set of internal modules that form the Nexe core.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from pathlib import Path
from typing import Dict, Optional, Set

# Core trust is granted by (name, canonical repo-relative path) pairs, not by
# name alone: a same-named directory anywhere else in the discovery paths must
# not inherit core trust (WS4-01). Only modules that actually ship with the
# repo are listed (B041).
_CORE_MODULE_PATHS: Dict[str, str] = {
  "security": "plugins/security",
  "ollama_module": "plugins/ollama_module",
  "rag": "memory/rag",
  "embeddings": "memory/embeddings",
  "memory": "memory/memory",
  "cli": "core/cli",
}

# D-L: admission nature (declared + canonical path). First-party plugins that
# live under plugins/ (security, ollama_module) stay plugins for the TOML
# enabled-list. The loader cannot be a plugin of itself (ADR-001 A6).
_CORE_NATURE_EXTRA: Dict[str, str] = {
  "module_manager": "personality/module_manager",
}

def get_core_modules() -> Set[str]:
  """
  Return the set of module names considered internal to the project.

  Returns:
    Set with the names of the modules loaded by default.
  """
  return set(_CORE_MODULE_PATHS)

def _path_is_canonical(
  module_path: object, project_root: Optional[object], expected: Optional[str]
) -> bool:
  if expected is None or project_root is None or module_path is None:
    return False
  try:
    relative = Path(str(module_path)).resolve().relative_to(Path(str(project_root)).resolve())
  except (ValueError, OSError):
    return False
  return relative.as_posix() == expected


def is_core_module_at(name: str, module_path: object, project_root: Optional[object]) -> bool:
  """
  Return True only when ``name`` is a core module AND ``module_path`` resolves
  to its canonical location under ``project_root``.

  Fails closed: unknown name, missing project_root, or a path outside the
  canonical location all return False.
  """
  return _path_is_canonical(module_path, project_root, _CORE_MODULE_PATHS.get(name))


def is_core_nature_at(name: str, module_path: object, project_root: Optional[object]) -> bool:
  """True when admission treats the module as CORE, not as a plugin (D-L).

  Declared and at the canonical path. ``memory/*`` and ``core/cli`` qualify.
  ``security`` / ``ollama_module`` do not: they live under ``plugins/`` and
  stay on the TOML enabled-list. ``module_manager`` qualifies because the
  loader cannot be a plugin of itself.
  """
  extra = _CORE_NATURE_EXTRA.get(name)
  if extra is not None:
    return _path_is_canonical(module_path, project_root, extra)
  expected = _CORE_MODULE_PATHS.get(name)
  if expected is None:
    return False
  if not (expected.startswith("memory/") or expected.startswith("core/")):
    return False
  return _path_is_canonical(module_path, project_root, expected)
