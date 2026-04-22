"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/cli/module.py
Description: Classe principal del mòdul CLI Central Nexe. Gestiona la
             descoberta i execució de CLIs de mòduls.

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
    Retorna el banner ASCII del CLI Central Nexe.

    Reutilitza el logo canònic `NEXE_LOGO` definit a `core.cli.output`
    (el que `print_banner()` ja mostra a tots els altres punts d'entrada
    del CLI), evitant tenir dos banners divergents. El banner anterior
    d'aquesta funció era un residu d'"NAT 7" heretat del projecte
    original i no coincidia amb el logo canònic `server-nexe`.

    Returns:
      str: Banner ASCII oficial + subtítol.
    """
    return f"{NEXE_LOGO}\nCLI Central - Module Orchestrator\n"

  def greet(self, name: str = "Nexe", lang: Optional[str] = None) -> str:
    """
    Genera un missatge de benvinguda localitzat amb el banner ASCII.

    Les claus `cli.greetings.hello` i `cli.greetings.welcome` es
    resolen via `core.cli.i18n.t`, que llegeix
    `core/cli/languages/{lang}/common.json` amb fallback a ca-ES.

    Args:
      name: Nom a saludar.
      lang: Codi d'idioma (`ca-ES`, `es-ES`, `en-US`). Si és None s'obté
        de la variable d'entorn `NEXE_LANG`; per defecte `ca-ES`.

    Returns:
      str: Missatge de benvinguda amb el banner ASCII.
    """
    hello = t("cli.greetings.hello", lang=lang, default="Hola")
    welcome = t("cli.greetings.welcome", lang=lang, default="Benvingut al CLI Central Nexe")
    return f"{self.get_ascii_art()}\n{hello} {name}! {welcome}"