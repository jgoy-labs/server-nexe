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

def get_core_modules() -> Set[str]:
  """
  Return the set of module names considered internal to the project.

  Returns:
    Set with the names of the modules loaded by default.
  """
  return set(_CORE_MODULE_PATHS)

def is_core_module_at(name: str, module_path: object, project_root: Optional[object]) -> bool:
  """
  Return True only when ``name`` is a core module AND ``module_path`` resolves
  to its canonical location under ``project_root``.

  Fails closed: unknown name, missing project_root, or a path outside the
  canonical location all return False.
  """
  expected = _CORE_MODULE_PATHS.get(name)
  if expected is None or project_root is None or module_path is None:
    return False
  try:
    relative = Path(str(module_path)).resolve().relative_to(Path(str(project_root)).resolve())
  except (ValueError, OSError):
    return False
  return relative.as_posix() == expected
