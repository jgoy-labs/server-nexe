"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: core/cli/router.py
Description: str # Descripció curta

www.jgoy.net
────────────────────────────────────
"""

import logging
import os
import sys
import subprocess
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

try:
  import tomllib
except ImportError:
  import tomli as tomllib

@dataclass
class CLIInfo:
  """Informació d'un CLI de mòdul."""
  alias: str
  module_name: str
  entry_point: str
  description: str
  commands: List[str] = field(default_factory=list)
  framework: str = "argparse"
  offline: bool = True
  quadrant: str = ""
  manifest_path: str = ""

  def to_dict(self) -> dict:
    """Convert to dictionary."""
    return {
      "alias": self.alias,
      "module": self.module_name,
      "entry_point": self.entry_point,
      "description": self.description,
      "commands": self.commands,
      "framework": self.framework,
      "offline": self.offline,
      "quadrant": self.quadrant,
    }

DEFAULT_CLIS: Dict[str, CLIInfo] = {
  "chat": CLIInfo(
    alias="chat",
    module_name="cli",
    entry_point="core.cli.chat_cli",
    description="Chat interactiu unificat (Automàtic: MLX, Llama.cpp o Ollama)",
    commands=["--system", "--rag", "--engine"],
    framework="click",
    offline=False,
    quadrant="core",
  ),
  "logs": CLIInfo(
    alias="logs",
    module_name="cli",
    entry_point="core.cli.log_viewer",
    description="Veure els logs del sistema en temps real (tail -f)",
    commands=["--module", "--last"],
    framework="click",
    offline=True,
    quadrant="core",
  ),
  "memory": CLIInfo(
    alias="memory",
    module_name="memory",
    entry_point="memory.memory.cli",
    description="Gestió de memòria plana i ingesta de dades",
    commands=["store", "recall", "stats", "cleanup"],
    framework="argparse",
    offline=True,
    quadrant="memory",
  ),
  "rag": CLIInfo(
    alias="rag",
    module_name="rag",
    entry_point="memory.rag.cli",
    description="Gestió del motor RAG i vectors",
    commands=["search", "index", "status"],
    framework="argparse",
    offline=True,
    quadrant="memory",
  ),
}

class CLIRouter:
  """
  Router que descobreix i executa CLIs de mòduls Nexe.

  Estratègia:
  1. Primer intenta descobrir via manifest.toml
  2. Si no troba, usa el registre hardcoded
  3. Executa via subprocess per aïllament
  """

  def __init__(self, project_root: Optional[Path] = None):
    """
    Initialize router.

    Args:
      project_root: Arrel del projecte Nexe (default: detecta automàticament)
    """
    self._project_root = project_root or self._detect_project_root()
    self._cache: Dict[str, CLIInfo] = {}
    self._discovered = False

  def _detect_project_root(self) -> Path:
    """Detecta l'arrel del projecte Nexe."""
    current = Path(__file__).resolve()

    for parent in current.parents:
      if (parent / "personality").is_dir() and (parent / "plugins").is_dir():
        return parent
      if (parent / "pyproject.toml").exists():
        return parent

    return Path.cwd()

  def discover_all(self) -> List[CLIInfo]:
    """
    Descobreix tots els CLIs disponibles.

    Returns:
      Llista de CLIInfo per cada CLI descobert
    """
    if not self._discovered:
      self._discover_from_manifests()
      self._discovered = True

    return list(self._cache.values())

  def _discover_from_manifests(self) -> None:
    """Descobreix CLIs des dels manifest.toml dels mòduls."""
    self._cache = DEFAULT_CLIS.copy()

    quadrants = ["memory", "plugins", "personality", "core"]

    for quadrant in quadrants:
      quadrant_path = self._project_root / quadrant
      if not quadrant_path.exists():
        continue

      for manifest_path in quadrant_path.rglob("manifest.toml"):
        try:
          cli_info = self._parse_manifest(manifest_path, quadrant)
          if cli_info:
            self._cache[cli_info.alias] = cli_info
        except (OSError, KeyError, ValueError) as e:
          logger.debug("Skip manifest %s: %s", manifest_path, e)
          continue

  def _parse_manifest(self, manifest_path: Path, quadrant: str) -> Optional[CLIInfo]:
    """
    Parseja un manifest.toml i extreu info del CLI.

    Args:
      manifest_path: Path al manifest.toml
      quadrant: Quadrant Nexe (plugins, memory, etc.)

    Returns:
      CLIInfo si el manifest defineix un CLI, None altrament
    """
    with open(manifest_path, "rb") as f:
      data = tomllib.load(f)

    module_data = data.get("module", {})
    cli_data = module_data.get("cli", {})

    if not cli_data:
      return None

    alias = cli_data.get("command_name", cli_data.get("alias", ""))
    entry_point = cli_data.get("entry_point", "")
    description = cli_data.get("description", "")
    commands = cli_data.get("commands", [])
    framework = cli_data.get("framework", "argparse")
    offline = cli_data.get("offline", True)

    if not alias or not entry_point:
      return None

    module_name = module_data.get("name", alias)

    return CLIInfo(
      alias=alias,
      module_name=module_name,
      entry_point=entry_point,
      description=description,
      commands=commands,
      framework=framework,
      offline=offline,
      quadrant=quadrant,
      manifest_path=str(manifest_path),
    )

  def get_cli(self, alias: str) -> Optional[CLIInfo]:
    """
    Obté informació d'un CLI per alias.

    Args:
      alias: Nom curt del CLI (memory, rag, etc.)

    Returns:
      CLIInfo si existeix, None altrament
    """
    if not self._discovered:
      self._discover_from_manifests()
      self._discovered = True

    return self._cache.get(alias)

  def execute(self, alias: str, args: List[str]) -> int:
    """
    Executa un CLI de mòdul via subprocess.

    Args:
      alias: Nom del CLI (memory, rag, etc.)
      args: Arguments a passar al CLI

    Returns:
      Exit code del subprocess
    """
    cli_info = self.get_cli(alias)
    if cli_info is None:
      print(f"Error: CLI '{alias}' not found", file=sys.stderr)
      return 1

    cmd = [
      sys.executable,
      "-m",
      cli_info.entry_point,
    ] + args

    env = os.environ.copy()
    existing_path = env.get("PYTHONPATH")
    if existing_path:
      env["PYTHONPATH"] = f"{existing_path}{os.pathsep}{self._project_root}"
    else:
      env["PYTHONPATH"] = str(self._project_root)

    try:
      result = subprocess.run(
        cmd,
        cwd=str(self._project_root),
        env=env,
      )
      return result.returncode

    except FileNotFoundError:
      print(f"Error: Python interpreter not found: {sys.executable}", file=sys.stderr)
      return 1
    except Exception as e:
      print(f"Error executing CLI '{alias}': {e}", file=sys.stderr)
      return 1

  def get_all_clis_dict(self) -> dict:
    """
    Retorna tots els CLIs com a diccionari (per API).

    Returns:
      Dict amb total i llista de CLIs
    """
    clis = self.discover_all()
    return {
      "total": len(clis),
      "clis": [cli.to_dict() for cli in clis]
    }

_router_instance: Optional[CLIRouter] = None

def get_router() -> CLIRouter:
  """Get singleton router instance."""
  global _router_instance
  if _router_instance is None:
    _router_instance = CLIRouter()
  return _router_instance
