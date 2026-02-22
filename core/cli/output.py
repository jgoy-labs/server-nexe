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

NEXE_BANNER = "[bold red]" + NEXE_LOGO + "[/bold red]\nCLI Central - Orquestrador de Mòduls"

def print_banner():
  """Print Nexe CLI banner."""
  if RICH_AVAILABLE:
    console.print(Panel(
      NEXE_BANNER,
      title="[bold red]server-nexe[/bold red]",
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
      title="Mòduls amb CLI Disponibles",
      box=box.ROUNDED,
      show_header=True,
      header_style="bold cyan",
    )

    table.add_column("Alias", style="green", width=10)
    table.add_column("Mòdul", style="white", width=15)
    table.add_column("Descripció", style="dim", width=35)
    table.add_column("Comandes", style="yellow", width=25)
    table.add_column("Offline", style="cyan", width=8)

    for cli in sorted(clis, key=lambda c: c.alias):
      offline_icon = "[green]Yes[/green]" if cli.offline else "[red]No[/red]"
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
    console.print("[dim]Ús: nexe <alias> <comanda> [args][/dim]")
    console.print("[dim]Exemple: nexe chat --rag[/dim]")

  else:
    print("\nMòduls amb CLI Disponibles")
    print("=" * 60)
    print(f"{'Alias':<10} {'Mòdul':<15} {'Comandes':<30}")
    print("-" * 60)
    for cli in sorted(clis, key=lambda c: c.alias):
      commands = ", ".join(cli.commands[:3])
      print(f"{cli.alias:<10} {cli.module_name:<15} {commands:<30}")
    print()
    print("Ús: nexe <alias> <comanda> [args]")

def print_status(status_data: Dict[str, Any]):
  """
  Print system status.

  Args:
    status_data: Status dictionary from server
  """
  if RICH_AVAILABLE:
    server_status = status_data.get("server", {})
    server_online = server_status.get("online", False)
    status_icon = "[green]ONLINE[/green]" if server_online else "[red]OFFLINE[/red]"

    console.print()
    console.print(Panel(
      f"Servidor: {status_icon}\n"
      f"URL: {status_data.get('url', 'N/A')}\n"
      f"Versió: {status_data.get('version', 'N/A')}",
      title="[bold]Estat del Sistema Nexe[/bold]",
      border_style="cyan",
    ))

    modules = status_data.get("modules", [])
    if modules:
      table = Table(box=box.SIMPLE, show_header=True)
      table.add_column("Mòdul", style="white")
      table.add_column("Estat", style="green")

      for mod in modules:
        name = mod.get("name", "?")
        state = mod.get("state", "?")
        state_color = "green" if state == "LOADED" else "yellow" if state == "WARM" else "red"
        table.add_row(name, f"[{state_color}]{state}[/{state_color}]")

      console.print(table)

  else:
    print("\nEstat del Sistema Nexe")
    print("=" * 40)
    server_online = status_data.get("server", {}).get("online", False)
    print(f"Servidor: {'ONLINE' if server_online else 'OFFLINE'}")
    print(f"URL: {status_data.get('url', 'N/A')}")
    print(f"Versió: {status_data.get('version', 'N/A')}")

def print_error(message: str):
  """Print error message."""
  if RICH_AVAILABLE:
    console.print(f"[bold red]Error:[/bold red] {message}")
  else:
    print(f"Error: {message}")