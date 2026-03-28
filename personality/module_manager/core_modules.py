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
  Retorna el conjunt de noms de mòduls que es consideren interns del projecte.

  Returns:
    Set amb els noms dels mòduls que es carreguen per defecte.
  """
  return set(_CORE_MODULES)