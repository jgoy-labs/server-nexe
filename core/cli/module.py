"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/cli/module.py
Description: Main class of the Nexe Central CLI module. Manages the
             discovery and execution of module CLIs.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from pathlib import Path
from typing import List, Dict, Any, Optional

from .router import CLIRouter, CLIInfo
from .config import NexeConfig
from .output import NEXE_LOGO
from .i18n import t

class CLIModule:
  """
  Main class for the Nexe Central CLI.

  Provides an object-oriented interface for managing
  the discovery and execution of Nexe module CLIs.
  """

  name = "cli"
  version = "1.0.0"
  description = "Nexe Central CLI - Module CLI orchestrator"

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
    Return the ASCII banner for the Nexe Central CLI.

    Reuses the canonical `NEXE_LOGO` defined in `core.cli.output`
    (the one that `print_banner()` already shows at all other CLI entry
    points), avoiding two diverging banners. The previous banner in this
    function previously used a legacy banner from an earlier project version
    and did not match the canonical `server-nexe` logo.

    Returns:
      str: Official ASCII banner + subtitle.
    """
    return f"{NEXE_LOGO}\nCLI Central - Module Orchestrator\n"

  def greet(self, name: str = "Nexe", lang: Optional[str] = None) -> str:
    """
    Generate a localised welcome message with the ASCII banner.

    The keys `cli.greetings.hello` and `cli.greetings.welcome` are
    resolved via `core.cli.i18n.t`, which reads
    `core/cli/languages/{lang}/common.json` with fallback to ca-ES.

    Args:
      name: Name to greet.
      lang: Language code (`ca-ES`, `es-ES`, `en-US`). If None, obtained
        from the `NEXE_LANG` environment variable; defaults to `ca-ES`.

    Returns:
      str: Welcome message with the ASCII banner.
    """
    hello = t("cli.greetings.hello", lang=lang, default="Hola")
    welcome = t("cli.greetings.welcome", lang=lang, default="Benvingut al CLI Central Nexe")
    return f"{self.get_ascii_art()}\n{hello} {name}! {welcome}"
