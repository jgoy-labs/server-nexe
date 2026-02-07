"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: core/cli/module.py
Description: Main class for the Nexe Central CLI module. Handles discovery

www.jgoy.net
────────────────────────────────────
"""

from pathlib import Path
from typing import List, Dict, Any, Optional

from .router import CLIRouter, CLIInfo
from .config import NexeConfig
from .i18n import t

class CLIModule:
  """
  Main class for the Nexe Central CLI.

  Provides an object-oriented interface to manage
  discovery and execution of Nexe module CLIs.
  """

  name = "cli"
  version = "1.0.0"
  description = t("cli.description", "CLI Central Nexe - Module CLI Orchestrator")

  def __init__(self, config: Optional[NexeConfig] = None):
    """
    Initialize CLI module.

    Args:
      config: Optional configuration object
    """
    self.config = config or NexeConfig()
    self._router = CLIRouter()
    self._module_path = Path(__file__).parent

  def get_info(self) -> Dict[str, Any]:
    """
    Get module information.

    Returns:
      dict: Module info including name, version, and capabilities
    """
    clis = self._router.discover_all()

    return {
      "name": self.name,
      "version": self.version,
      "description": self.description,
      "path": str(self._module_path),
      "quadrant": "core",
      "capabilities": {
        "cli_discovery": True,
        "subprocess_execution": True,
        "offline_support": True,
        "http_client": True
      },
      "clis_count": len(clis),
      "quadrants_covered": list(set(c.quadrant for c in clis if c.quadrant))
    }

  def discover_clis(self) -> List[CLIInfo]:
    """
    Discover all available CLIs.

    Returns:
      List of CLIInfo objects
    """
    return self._router.discover_all()

  def get_cli(self, alias: str) -> Optional[CLIInfo]:
    """
    Get CLI by alias.

    Args:
      alias: CLI alias (memory, auto_clean, etc.)

    Returns:
      CLIInfo if found, None otherwise
    """
    return self._router.get_cli(alias)

  def execute(self, alias: str, args: List[str]) -> int:
    """
    Execute a CLI by alias.

    Args:
      alias: CLI alias
      args: Arguments to pass

    Returns:
      Exit code from subprocess
    """
    return self._router.execute(alias, args)

  def get_ascii_art(self) -> str:
    """
    Get ASCII art banner for CLI.

    Returns:
      str: ASCII art banner
    """
    return """
 _  _  _ _____  __  ______
| \\ | | / \\|_  _| / / |____ |
| \\| | / _ \\ | | / /_   / /
| |\\ |/ ___ \\| | / /\\ \\  / /
|_| \\_/_/  \\_\\_|/_/ \\_\\ /_/
"""

  def greet(self, name: str = "Nexe") -> str:
    """
    Generate a greeting message.

    Args:
      name: Name to greet

    Returns:
      str: Greeting message with ASCII art
    """
    hello = t("cli.greetings.hello", "Hello")
    welcome = t("cli.greetings.welcome", "Welcome to CLI Central Nexe 0.8")
    return f"{self.get_ascii_art()}\n{hello} {name}! {welcome}."
