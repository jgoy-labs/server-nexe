"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: core/cli/output.py
Description: Output formatting per CLI Central Nexe.

www.jgoy.net
────────────────────────────────────
"""

from typing import List, Dict, Any

try:
  from rich.console import Console
  from rich.table import Table
  from rich.panel import Panel
  from rich import box
  RICH_AVAILABLE = True
except ImportError:
  RICH_AVAILABLE = False

from .router import CLIInfo
from .i18n import t

if RICH_AVAILABLE:
  console = Console()
else:
  class FallbackConsole:
    def print(self, *args, **kwargs):
      text = " ".join(str(a) for a in args)
      print(text)

  console = FallbackConsole()

NEXE_LOGO = """
      _                                               
     / /  ___  ___ _ ____   _____ _ __    _ __   _____  __  ___ 
    / /  / __|/ _ \ '__\ \ / / _ \ '__|  | '_ \ / _ \ \ \/ / _ \\
   / /   \__ \  __/ |   \ V /  __/ |  _  | | | |  __/>  <  __/ 
  /_/    |___/\___|_|    \_/ \___|_| (_) |_| |_|\___/_/\_\\___| 
"""

NEXE_BANNER = "[bold red]" + NEXE_LOGO + "[/bold red]\n" + t(
  "cli.output.banner_subtitle",
  "CLI Central - Module Orchestrator"
)

def print_banner():
  """Print Nexe CLI banner."""
  if RICH_AVAILABLE:
    console.print(Panel(
      NEXE_BANNER,
      title=f"[bold red]{t('cli.output.banner_title', 'server.nexe')}[/bold red]",
      border_style="red",
      box=box.ROUNDED,
    ))
  else:
    print(NEXE_BANNER)
    print("=" * 50)

def print_modules_table(clis: List[CLIInfo]):
  """
  Print table of available CLI modules.

  Args:
    clis: List of CLIInfo objects
  """
  if RICH_AVAILABLE:
    table = Table(
      title=t("cli.output.modules_title", "CLI Modules Available"),
      box=box.ROUNDED,
      show_header=True,
      header_style="bold cyan",
    )

    table.add_column(t("cli.output.columns.alias", "Alias"), style="green", width=10)
    table.add_column(t("cli.output.columns.module", "Module"), style="white", width=15)
    table.add_column(t("cli.output.columns.description", "Description"), style="dim", width=35)
    table.add_column(t("cli.output.columns.commands", "Commands"), style="yellow", width=25)
    table.add_column(t("cli.output.columns.offline", "Offline"), style="cyan", width=8)

    for cli in sorted(clis, key=lambda c: c.alias):
      yes_label = t("cli.output.offline.yes", "Yes")
      no_label = t("cli.output.offline.no", "No")
      offline_icon = f"[green]{yes_label}[/green]" if cli.offline else f"[red]{no_label}[/red]"
      commands = ", ".join(cli.commands[:4])
      if len(cli.commands) > 4:
        commands += "..."

      table.add_row(
        cli.alias,
        cli.module_name,
        cli.description[:35] + "..." if len(cli.description) > 35 else cli.description,
        commands,
        offline_icon,
      )

    console.print(table)
    console.print()
    console.print(f"[dim]{t('cli.output.usage', 'Usage: nexe <alias> <command> [args]')}[/dim]")
    console.print(f"[dim]{t('cli.output.example', 'Example: nexe chat --rag')}[/dim]")

  else:
    print(f"\n{t('cli.output.modules_title', 'CLI Modules Available')}")
    print("=" * 60)
    print(f"{t('cli.output.columns.alias', 'Alias'):<10} {t('cli.output.columns.module', 'Module'):<15} {t('cli.output.columns.commands', 'Commands'):<30}")
    print("-" * 60)
    for cli in sorted(clis, key=lambda c: c.alias):
      commands = ", ".join(cli.commands[:3])
      print(f"{cli.alias:<10} {cli.module_name:<15} {commands:<30}")
    print()
    print(t("cli.output.usage", "Usage: nexe <alias> <command> [args]"))

def print_status(status_data: Dict[str, Any]):
  """
  Print system status.

  Args:
    status_data: Status dictionary from server
  """
  if RICH_AVAILABLE:
    server_status = status_data.get("server", {})
    server_online = server_status.get("online", False)
    online_label = t("cli.output.server.online", "ONLINE")
    offline_label = t("cli.output.server.offline", "OFFLINE")
    status_icon = f"[green]{online_label}[/green]" if server_online else f"[red]{offline_label}[/red]"

    console.print()
    console.print(Panel(
      f"{t('cli.output.labels.server', 'Server')}: {status_icon}\n"
      f"{t('cli.output.labels.url', 'URL')}: {status_data.get('url', 'N/A')}\n"
      f"{t('cli.output.labels.version', 'Version')}: {status_data.get('version', 'N/A')}",
      title=f"[bold]{t('cli.output.status_title', 'Nexe System Status')}[/bold]",
      border_style="cyan",
    ))

    modules = status_data.get("modules", [])
    if modules:
      table = Table(box=box.SIMPLE, show_header=True)
      table.add_column(t("cli.output.labels.module", "Module"), style="white")
      table.add_column(t("cli.output.labels.state", "State"), style="green")

      for mod in modules:
        name = mod.get("name", "?")
        state = mod.get("state", "?")
        state_color = "green" if state == "LOADED" else "yellow" if state == "WARM" else "red"
        table.add_row(name, f"[{state_color}]{state}[/{state_color}]")

      console.print(table)

  else:
    print(f"\n{t('cli.output.status_title', 'Nexe System Status')}")
    print("=" * 40)
    server_online = status_data.get("server", {}).get("online", False)
    online_label = t("cli.output.server.online", "ONLINE")
    offline_label = t("cli.output.server.offline", "OFFLINE")
    print(f"{t('cli.output.labels.server', 'Server')}: {online_label if server_online else offline_label}")
    print(f"{t('cli.output.labels.url', 'URL')}: {status_data.get('url', 'N/A')}")
    print(f"{t('cli.output.labels.version', 'Version')}: {status_data.get('version', 'N/A')}")

def print_error(message: str):
  """Print error message."""
  if RICH_AVAILABLE:
    console.print(f"[bold red]{t('cli.output.error_prefix', 'Error')}:[/bold red] {message}")
  else:
    print(f"{t('cli.output.error_prefix', 'Error')}: {message}")
