"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: plugins/ollama_module/cli.py
Description: CLI per Ollama module - Permet gestionar models LLM locals i fer

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import sys
import asyncio
from typing import Optional

try:
  import typer
  from rich.console import Console
  from rich.table import Table
  from rich.progress import Progress, SpinnerColumn, TextColumn
  from rich.panel import Panel
  RICH_AVAILABLE = True
except ImportError:
  RICH_AVAILABLE = False
  typer = None

from ..module import OllamaModule

if typer:
  app = typer.Typer(
    name="ollama",
    help="Gestió de models LLM locals amb Ollama",
    no_args_is_help=True
  )
else:
  app = None

console = Console() if RICH_AVAILABLE else None

def _run_async(coro):
  """Helper per executar coroutines en sync context"""
  return asyncio.run(coro)

@app.command()
def status():
  """Show Ollama connection status."""
  ollama = OllamaModule()

  console.print("\n[bold cyan]Ollama Status[/bold cyan]")
  console.print(f"URL: {ollama.base_url}")

  with console.status("[bold green]Comprovant connexió..."):
    connected = _run_async(ollama.check_connection())

  if connected:
    console.print("[green]Estat: CONNECTAT[/green]")

    try:
      models = _run_async(ollama.list_models())
      console.print(f"Models: {len(models)}")
    except Exception:
      console.print("Models: Error obtenint llista")
  else:
    console.print("[red]Estat: DESCONNECTAT[/red]")
    console.print("\n[yellow]Per iniciar Ollama:[/yellow]")
    console.print(" ollama serve")

@app.command()
def models():
  """Llista els models disponibles localment"""
  ollama = OllamaModule()

  with console.status("[bold green]Obtenint models..."):
    try:
      model_list = _run_async(ollama.list_models())
    except Exception as e:
      console.print(f"[red]Error: {e}[/red]")
      console.print("[yellow]Make sure Ollama is running: ollama serve[/yellow]")
      raise typer.Exit(1)

  if not model_list:
    console.print("[yellow]No models installed[/yellow]")
    console.print("\nPer descarregar un model:")
    console.print(" nexe ollama pull mistral")
    console.print(" nexe ollama pull llama3.2")
    return

  table = Table(title="Local Ollama Models")
  table.add_column("Model", style="cyan")
  table.add_column("Size", justify="right", style="green")
  table.add_column("Modified", style="dim")

  for model in model_list:
    name = model.get("name", "unknown")
    size = model.get("size", 0)
    size_gb = f"{size / (1024**3):.2f} GB"
    modified = model.get("modified_at", "")[:10] if model.get("modified_at") else "-"

    table.add_row(name, size_gb, modified)

  console.print(table)
  console.print(f"\n[dim]Total: {len(model_list)} models[/dim]")

@app.command()
def pull(
  model: str = typer.Argument(..., help="Model name to download (e.g.: mistral, llama3.2)")
):
  """Download a model from Ollama"""
  ollama = OllamaModule()

  console.print(f"\n[bold cyan]Downloading model: {model}[/bold cyan]")

  async def do_pull():
    last_status = ""
    with Progress(
      SpinnerColumn(),
      TextColumn("[progress.description]{task.description}"),
      console=console
    ) as progress:
      task = progress.add_task(f"Downloading {model}...", total=None)

      async for chunk in ollama.pull_model(model):
        status = chunk.get("status", "")
        if status != last_status:
          progress.update(task, description=status)
          last_status = status

        if "completed" in chunk and "total" in chunk:
          completed = chunk["completed"]
          total = chunk["total"]
          pct = (completed / total * 100) if total > 0 else 0
          progress.update(task, description=f"{status} ({pct:.1f}%)")

  try:
    _run_async(do_pull())
    console.print(f"[green]Model {model} downloaded successfully![/green]")
  except Exception as e:
    console.print(f"[red]Error: {e}[/red]")
    raise typer.Exit(1)

@app.command()
def info(
  model: str = typer.Argument(..., help="Model name")
):
  """Show detailed information about a model."""
  ollama = OllamaModule()

  with console.status(f"[bold green]Getting info for {model}..."):
    try:
      model_info = _run_async(ollama.get_model_info(model))
    except Exception as e:
      console.print(f"[red]Error: {e}[/red]")
      raise typer.Exit(1)

  console.print(Panel(f"[bold cyan]{model}[/bold cyan]", title="Model Info"))

  if "parameters" in model_info:
    console.print("\n[bold]Parameters:[/bold]")
    console.print(model_info["parameters"][:500] + "..." if len(model_info.get("parameters", "")) > 500 else model_info.get("parameters", "N/A"))

  if "template" in model_info:
    console.print("\n[bold]Template:[/bold]")
    template = model_info["template"]
    if len(template) > 300:
      template = template[:300] + "..."
    console.print(f"[dim]{template}[/dim]")

  details = model_info.get("details", {})
  if details:
    console.print("\n[bold]Details:[/bold]")
    for key, value in details.items():
      console.print(f" {key}: {value}")

@app.command()
def delete(
  model: str = typer.Argument(..., help="Model name to delete"),
  force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation")
):
  """Delete a local model"""
  ollama = OllamaModule()

  if not force:
    confirm = typer.confirm(f"Are you sure you want to delete model '{model}'?")
    if not confirm:
      console.print("[yellow]Operation cancelled[/yellow]")
      raise typer.Exit(0)

  with console.status(f"[bold red]Deleting {model}..."):
    try:
      _run_async(ollama.delete_model(model))
      console.print(f"[green]Model {model} deleted successfully[/green]")
    except Exception as e:
      console.print(f"[red]Error: {e}[/red]")
      raise typer.Exit(1)

@app.command()
def chat(
  model: str = typer.Argument("mistral", help="Model to use for chat"),
  system: Optional[str] = typer.Option(None, "--system", "-s", help="Initial system message")
):
  """Start an interactive chat with an LLM model"""
  ollama = OllamaModule()

  with console.status("[bold green]Connectant amb Ollama..."):
    if not _run_async(ollama.check_connection()):
      console.print("[red]Error: Ollama is not available[/red]")
      console.print("[yellow]Start Ollama with: ollama serve[/yellow]")
      raise typer.Exit(1)

  console.print(Panel(
    f"[bold cyan]Chat with {model}[/bold cyan]\n"
    "[dim]Type 'exit' or 'quit' to leave\n"
    "Type 'clear' to reset history[/dim]",
    title="Nexe Ollama Chat"
  ))

  messages = []

  if system:
    messages.append({"role": "system", "content": system})
    console.print(f"[dim]Sistema: {system}[/dim]\n")

  while True:
    try:
      user_input = console.input("[bold green]Tu:[/bold green] ")

      if not user_input.strip():
        continue

      if user_input.lower() in ("exit", "quit", "q"):
        console.print("[dim]Goodbye![/dim]")
        break

      if user_input.lower() == "clear":
        messages = []
        if system:
          messages.append({"role": "system", "content": system})
        console.print("[dim]History cleared[/dim]\n")
        continue

      messages.append({"role": "user", "content": user_input})

      console.print(f"[bold cyan]{model}:[/bold cyan] ", end="")

      full_response = ""

      async def get_response():
        nonlocal full_response
        async for chunk in ollama.chat(model, messages, stream=True):
          if "message" in chunk:
            content = chunk["message"].get("content", "")
            full_response += content
            print(content, end="", flush=True)

      _run_async(get_response())
      print()

      messages.append({"role": "assistant", "content": full_response})
      print()

    except KeyboardInterrupt:
      console.print("\n[dim]Interrupted. Goodbye![/dim]")
      break
    except Exception as e:
      console.print(f"\n[red]Error: {e}[/red]")

@app.command()
def ask(
  prompt: str = typer.Argument(..., help="Question to ask the model"),
  model: str = typer.Option("mistral", "--model", "-m", help="Model to use"),
  system: Optional[str] = typer.Option(None, "--system", "-s", help="System message")
):
  """Ask the model a quick one-shot question (no interactive chat)."""
  ollama = OllamaModule()

  with console.status("[bold green]Connecting..."):
    if not _run_async(ollama.check_connection()):
      console.print("[red]Error: Ollama is not available[/red]")
      raise typer.Exit(1)

  messages = []
  if system:
    messages.append({"role": "system", "content": system})
  messages.append({"role": "user", "content": prompt})

  console.print(f"\n[bold green]Question:[/bold green] {prompt}")
  console.print(f"\n[bold cyan]Answer ({model}):[/bold cyan]")

  async def get_response():
    async for chunk in ollama.chat(model, messages, stream=True):
      if "message" in chunk:
        content = chunk["message"].get("content", "")
        print(content, end="", flush=True)

  try:
    _run_async(get_response())
    print("\n")
  except Exception as e:
    console.print(f"\n[red]Error: {e}[/red]")
    raise typer.Exit(1)

def main():
  """Entry point del CLI"""
  if not typer or not RICH_AVAILABLE:
    print("Error: Requereix 'typer' i 'rich'. Instal·la amb:")
    print(" pip install typer rich")
    sys.exit(1)

  app()

if __name__ == "__main__":
  main()