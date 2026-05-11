"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: personality/module_manager/core_modules.py
Description: Defines the set of internal modules that form the Nexe core.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from typing import Set

_CORE_MODULES: Set[str] = {
  "security",
  "observability",
  "workflow_engine",
  "ui_control_center",
  "ollama_module",
  "rag",
  "demo_module",
  "system_testing",
  "auto_clean",
  "embeddings",
  "memory",
  "tool_manager",
  "cli",
  "monitor_system",
  "memory",
}

def get_core_modules() -> Set[str]:
  """
  Return the set of module names considered internal to the project.

  Returns:
    Set with the names of the modules loaded by default.
  """
  return set(_CORE_MODULES)