"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: core/cli/router.py
Description: CLI router — dispatches commands to registered CLI modules.

www.jgoy.net · https://server-nexe.org
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
  """Information about a module CLI."""
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
    description="Unified interactive chat (Auto-selects: MLX, Llama.cpp or Ollama)",
    commands=["--system", "--rag", "--engine"],
    framework="click",
    offline=False,
    quadrant="core",
  ),
  "logs": CLIInfo(
    alias="logs",
    module_name="cli",
    entry_point="core.cli.log_viewer",
    description="View system logs in real time (tail -f)",
    commands=["--module", "--last"],
    framework="click",
    offline=True,
    quadrant="core",
  ),
  "memory": CLIInfo(
    alias="memory",
    module_name="memory",
    entry_point="memory.memory.cli",
    description="Flat memory management and data ingestion",
    commands=["store", "recall", "stats", "cleanup"],
    framework="argparse",
    offline=True,
    quadrant="memory",
  ),
  "rag": CLIInfo(
    alias="rag",
    module_name="rag",
    entry_point="memory.rag.cli",
    description="RAG engine and vector management",
    commands=["search", "index", "status"],
    framework="argparse",
    offline=True,
    quadrant="memory",
  ),
}

class CLIRouter:
  """
  Router that discovers and executes Nexe module CLIs.

  Strategy:
  1. First attempts discovery via manifest.toml
  2. Falls back to the hardcoded registry
  3. Executes via subprocess for isolation
  """

  def __init__(self, project_root: Optional[Path] = None):
    """
    Initialize router.

    Args:
      project_root: Nexe project root (default: auto-detected)
    """
    self._project_root = project_root or self._detect_project_root()
    self._cache: Dict[str, CLIInfo] = {}
    self._discovered = False

  def _detect_project_root(self) -> Path:
    """Detect the Nexe project root."""
    current = Path(__file__).resolve()

    for parent in current.parents:
      if (parent / "personality").is_dir() and (parent / "plugins").is_dir():
        return parent
      if (parent / "pyproject.toml").exists():
        return parent

    return Path.cwd()

  def discover_all(self) -> List[CLIInfo]:
    """
    Discover all available CLIs.

    Returns:
      List of CLIInfo for each discovered CLI
    """
    if not self._discovered:
      self._discover_from_manifests()
      self._discovered = True

    return list(self._cache.values())

  def _discover_from_manifests(self) -> None:
    """Discover CLIs from module manifest.toml files."""
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
    Parse a manifest.toml and extract CLI info.

    Args:
      manifest_path: Path to the manifest.toml
      quadrant: Nexe quadrant (plugins, memory, etc.)

    Returns:
      CLIInfo if the manifest defines a CLI, None otherwise
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
    Get CLI information by alias.

    Args:
      alias: Short CLI name (memory, rag, etc.)

    Returns:
      CLIInfo if it exists, None otherwise
    """
    if not self._discovered:
      self._discover_from_manifests()
      self._discovered = True

    return self._cache.get(alias)

  def execute(self, alias: str, args: List[str]) -> int:
    """
    Execute a module CLI via subprocess.

    Args:
      alias: CLI name (memory, rag, etc.)
      args: Arguments to pass to the CLI

    Returns:
      Subprocess exit code
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
    Return all CLIs as a dictionary (for API use).

    Returns:
      Dict with total count and list of CLIs
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
