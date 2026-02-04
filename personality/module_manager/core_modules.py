"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: personality/module_manager/core_modules.py
Description: Defineix el conjunt de mòduls interns que formen part del nucli de Nexe.

www.jgoy.net
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