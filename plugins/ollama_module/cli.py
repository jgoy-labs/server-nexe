"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: plugins/ollama_module/cli.py
Description: CLI per Ollama module - Permet gestionar models LLM locals i fer

www.jgoy.net
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

from .module import OllamaModule
from .i18n import get_i18n, t as _t

_I18N = get_i18n()

if typer:
  app = typer.Typer(
    name="ollama",
    help=_t("cli.app_help", "Manage local LLM models with Ollama"),
    no_args_is_help=True
  )
else:
  app = None

console = Console() if RICH_AVAILABLE else None

def _run_async(coro):
  """Helper per executar coroutines en sync context"""
  return asyncio.run(coro)

@app.command(help=_t("cli.commands.status_help", "Show Ollama connection status"))
def status():
  """Mostra l'estat de connexió amb Ollama"""
  ollama = OllamaModule(i18n=_I18N)

  console.print(f"\n[bold cyan]{_t('cli.status.title', 'Ollama Status')}[/bold cyan]")
  console.print(_t("cli.status.url", "URL: {url}", url=ollama.base_url))

  with console.status(f"[bold green]{_t('cli.status.checking', 'Checking connection...')}[/bold green]"):
    connected = _run_async(ollama.check_connection())

  if connected:
    console.print(f"[green]{_t('cli.status.connected', 'Status: CONNECTED')}[/green]")

    try:
      models = _run_async(ollama.list_models())
      console.print(_t("cli.status.models", "Models: {count}", count=len(models)))
    except Exception:
      console.print(_t("cli.status.models_error", "Models: Error fetching list"))
  else:
    console.print(f"[red]{_t('cli.status.disconnected', 'Status: DISCONNECTED')}[/red]")
    console.print(f"\n[yellow]{_t('cli.status.start_title', 'To start Ollama:')}[/yellow]")
    console.print(_t("cli.status.start_cmd", " ollama serve"))

@app.command(help=_t("cli.commands.models_help", "List locally available models"))
def models():
  """Llista els models disponibles localment"""
  ollama = OllamaModule(i18n=_I18N)

  with console.status(f"[bold green]{_t('cli.models.loading', 'Fetching models...')}[/bold green]"):
    try:
      model_list = _run_async(ollama.list_models())
    except Exception as e:
      console.print(f"[red]{_t('cli.common.error', 'Error: {error}', error=str(e))}[/red]")
      console.print(f"[yellow]{_t('cli.models.ensure_running', 'Make sure Ollama is running: ollama serve')}[/yellow]")
      raise typer.Exit(1)

  if not model_list:
    console.print(f"[yellow]{_t('cli.models.none', 'No models installed')}[/yellow]")
    console.print(f"\n{_t('cli.models.download_title', 'To download a model:')}")
    console.print(_t("cli.models.download_cmd1", " nexe ollama pull mistral"))
    console.print(_t("cli.models.download_cmd2", " nexe ollama pull llama3.2"))
    return

  table = Table(title=_t("cli.models.table_title", "Local Ollama Models"))
  table.add_column(_t("cli.models.col_model", "Model"), style="cyan")
  table.add_column(_t("cli.models.col_size", "Size"), justify="right", style="green")
  table.add_column(_t("cli.models.col_modified", "Modified"), style="dim")

  for model in model_list:
    name = model.get("name", "unknown")
    size = model.get("size", 0)
    size_gb = f"{size / (1024**3):.2f} GB"
    modified = model.get("modified_at", "")[:10] if model.get("modified_at") else "-"

    table.add_row(name, size_gb, modified)

  console.print(table)
  console.print(f"\n[dim]{_t('cli.models.total', 'Total: {count} models', count=len(model_list))}[/dim]")

@app.command(help=_t("cli.commands.pull_help", "Download an Ollama model"))
def pull(
  model: str = typer.Argument(..., help=_t("cli.pull.arg_model", "Model name to download (e.g. mistral, llama3.2)"))
):
  """Descarrega un model d'Ollama"""
  ollama = OllamaModule(i18n=_I18N)

  console.print(f"\n[bold cyan]{_t('cli.pull.title', 'Downloading model: {model}', model=model)}[/bold cyan]")

  async def do_pull():
    last_status = ""
    with Progress(
      SpinnerColumn(),
      TextColumn("[progress.description]{task.description}"),
      console=console
    ) as progress:
      task = progress.add_task(_t("cli.pull.task", "Downloading {model}...", model=model), total=None)

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
    console.print(f"[green]{_t('cli.pull.success', 'Model {model} downloaded successfully!', model=model)}[/green]")
  except Exception as e:
    console.print(f"[red]{_t('cli.common.error', 'Error: {error}', error=str(e))}[/red]")
    raise typer.Exit(1)

@app.command(help=_t("cli.commands.info_help", "Show detailed model information"))
def info(
  model: str = typer.Argument(..., help=_t("cli.info.arg_model", "Model name"))
):
  """Mostra informació detallada d'un model"""
  ollama = OllamaModule(i18n=_I18N)

  with console.status(f"[bold green]{_t('cli.info.loading', 'Fetching info for {model}...', model=model)}[/bold green]"):
    try:
      model_info = _run_async(ollama.get_model_info(model))
    except Exception as e:
      console.print(f"[red]{_t('cli.common.error', 'Error: {error}', error=str(e))}[/red]")
      raise typer.Exit(1)

  console.print(Panel(f"[bold cyan]{model}[/bold cyan]", title=_t("cli.info.panel_title", "Model Info")))

  if "parameters" in model_info:
    console.print(f"\n[bold]{_t('cli.info.parameters', 'Parameters:')}[/bold]")
    console.print(model_info["parameters"][:500] + "..." if len(model_info.get("parameters", "")) > 500 else model_info.get("parameters", "N/A"))

  if "template" in model_info:
    console.print(f"\n[bold]{_t('cli.info.template', 'Template:')}[/bold]")
    template = model_info["template"]
    if len(template) > 300:
      template = template[:300] + "..."
    console.print(f"[dim]{template}[/dim]")

  details = model_info.get("details", {})
  if details:
    console.print(f"\n[bold]{_t('cli.info.details', 'Details:')}[/bold]")
    for key, value in details.items():
      console.print(f" {key}: {value}")

@app.command(help=_t("cli.commands.delete_help", "Delete a local model"))
def delete(
  model: str = typer.Argument(..., help=_t("cli.delete.arg_model", "Model name to delete")),
  force: bool = typer.Option(False, "--force", "-f", help=_t("cli.delete.opt_force", "Do not ask for confirmation"))
):
  """Elimina un model local"""
  ollama = OllamaModule(i18n=_I18N)

  if not force:
    confirm = typer.confirm(_t("cli.delete.confirm", "Are you sure you want to delete model '{model}'?", model=model))
    if not confirm:
      console.print(f"[yellow]{_t('cli.delete.cancelled', 'Operation cancelled')}[/yellow]")
      raise typer.Exit(0)

  with console.status(f"[bold red]{_t('cli.delete.loading', 'Deleting {model}...', model=model)}[/bold red]"):
    try:
      _run_async(ollama.delete_model(model))
      console.print(f"[green]{_t('cli.delete.success', 'Model {model} deleted successfully', model=model)}[/green]")
    except Exception as e:
      console.print(f"[red]{_t('cli.common.error', 'Error: {error}', error=str(e))}[/red]")
      raise typer.Exit(1)

@app.command(help=_t("cli.commands.chat_help", "Start an interactive chat with a model"))
def chat(
  model: str = typer.Argument("mistral", help=_t("cli.chat.arg_model", "Model to use for chat")),
  system: Optional[str] = typer.Option(None, "--system", "-s", help=_t("cli.chat.opt_system", "Initial system message"))
):
  """Inicia un chat interactiu amb un model LLM"""
  ollama = OllamaModule(i18n=_I18N)

  with console.status(f"[bold green]{_t('cli.chat.connecting', 'Connecting to Ollama...')}[/bold green]"):
    if not _run_async(ollama.check_connection()):
      console.print(f"[red]{_t('cli.chat.not_available', 'Error: Ollama is not available')}[/red]")
      console.print(f"[yellow]{_t('cli.chat.start_hint', 'Start Ollama with: ollama serve')}[/yellow]")
      raise typer.Exit(1)

  panel_body = _t(
    "cli.chat.panel_body",
    "Chat with {model}\nType 'exit' or 'quit' to leave\nType 'clear' to clear history",
    model=model
  )
  panel_lines = panel_body.splitlines()
  panel_render = ""
  if panel_lines:
    panel_render = f"[bold cyan]{panel_lines[0]}[/bold cyan]"
  if len(panel_lines) > 1:
    panel_render += "\n[dim]" + "\n".join(panel_lines[1:]) + "[/dim]"

  console.print(Panel(
    panel_render,
    title=_t("cli.chat.panel_title", "Nexe Ollama Chat")
  ))

  messages = []

  if system:
    messages.append({"role": "system", "content": system})
    console.print(f"[dim]{_t('cli.chat.system', 'System: {system}', system=system)}[/dim]\n")

  while True:
    try:
      user_input = console.input(f"[bold green]{_t('cli.chat.prompt', 'You:')}[/bold green] ")

      if not user_input.strip():
        continue

      if user_input.lower() in ("exit", "quit", "q"):
        console.print(f"[dim]{_t('cli.chat.exit', 'Goodbye!')}[/dim]")
        break

      if user_input.lower() == "clear":
        messages = []
        if system:
          messages.append({"role": "system", "content": system})
        console.print(f"[dim]{_t('cli.chat.cleared', 'History cleared')}[/dim]\n")
        continue

      messages.append({"role": "user", "content": user_input})

      console.print(f"[bold cyan]{_t('cli.chat.model_prefix', '{model}:', model=model)}[/bold cyan] ", end="")

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
      console.print(f"\n[dim]{_t('cli.chat.interrupted', 'Interrupted. Goodbye!')}[/dim]")
      break
    except Exception as e:
      console.print(f"\n[red]{_t('cli.common.error', 'Error: {error}', error=str(e))}[/red]")

@app.command(help=_t("cli.commands.ask_help", "Ask a quick question without interactive chat"))
def ask(
  prompt: str = typer.Argument(..., help=_t("cli.ask.arg_prompt", "Question to ask the model")),
  model: str = typer.Option("mistral", "--model", "-m", help=_t("cli.ask.opt_model", "Model to use")),
  system: Optional[str] = typer.Option(None, "--system", "-s", help=_t("cli.ask.opt_system", "System message"))
):
  """Fa una pregunta ràpida al model (sense chat interactiu)"""
  ollama = OllamaModule(i18n=_I18N)

  with console.status(f"[bold green]{_t('cli.ask.connecting', 'Connecting...')}[/bold green]"):
    if not _run_async(ollama.check_connection()):
      console.print(f"[red]{_t('cli.ask.not_available', 'Error: Ollama is not available')}[/red]")
      raise typer.Exit(1)

  messages = []
  if system:
    messages.append({"role": "system", "content": system})
  messages.append({"role": "user", "content": prompt})

  console.print(f"\n[bold green]{_t('cli.ask.question_label', 'Question:')}[/bold green] {prompt}")
  console.print(f"\n[bold cyan]{_t('cli.ask.answer_label', 'Answer ({model}):', model=model)}[/bold cyan]")

  async def get_response():
    async for chunk in ollama.chat(model, messages, stream=True):
      if "message" in chunk:
        content = chunk["message"].get("content", "")
        print(content, end="", flush=True)

  try:
    _run_async(get_response())
    print("\n")
  except Exception as e:
    console.print(f"\n[red]{_t('cli.common.error', 'Error: {error}', error=str(e))}[/red]")
    raise typer.Exit(1)

def main():
  """Entry point del CLI"""
  if not typer or not RICH_AVAILABLE:
    print(_t("cli.deps.missing", "Error: Requires 'typer' and 'rich'. Install with:"))
    print(_t("cli.deps.install", " pip install typer rich"))
    sys.exit(1)

  app()

if __name__ == "__main__":
  main()
