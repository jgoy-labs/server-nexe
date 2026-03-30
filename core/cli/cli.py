"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: core/cli/cli.py
Description: Central Nexe CLI 0.8.5 - Main Click application.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import sys
import click
from typing import Optional, List

from .router import CLIRouter
from .output import print_banner, print_modules_table, print_status, print_error
from .config import NexeConfig

class DynamicGroup(click.Group):
  """
  Click Group that intercepts undefined commands and redirects them
  to the router to invoke module CLIs via subprocess.
  """

  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self._router = CLIRouter()

  def get_command(self, ctx: click.Context, cmd_name: str) -> Optional[click.Command]:
    """
    Attempts to find the command:
    1. First looks among registered commands (modules, status, etc.)
    2. If not found, looks among module CLIs
    """
    cmd = super().get_command(ctx, cmd_name)
    if cmd is not None:
      return cmd

    original_name = cmd_name
    extra_args = []
    if '/' in cmd_name:
      parts = cmd_name.split('/')
      cmd_name = parts[0]
      extra_args = parts[1:]

    cli_info = self._router.get_cli(cmd_name)
    if cli_info is None:
      return None

    @click.command(name=original_name, context_settings=dict(
      ignore_unknown_options=True,
      allow_extra_args=True,
      allow_interspersed_args=False,
    ))
    @click.argument('args', nargs=-1, type=click.UNPROCESSED)
    @click.pass_context
    def dynamic_cmd(ctx: click.Context, args: tuple):
      """Dynamic command that delegates to the module CLI."""
      all_args = list(extra_args) + list(args)

      exit_code = self._router.execute(cmd_name, all_args)
      ctx.exit(exit_code)

    dynamic_cmd.help = cli_info.description

    return dynamic_cmd

  def list_commands(self, ctx: click.Context) -> List[str]:
    """Returns all available commands (built-in + modules)."""
    builtin = super().list_commands(ctx)

    module_clis = [cli.alias for cli in self._router.discover_all()]

    return sorted(set(builtin + module_clis))

@click.group(cls=DynamicGroup, invoke_without_command=True)
@click.option('--version', '-V', is_flag=True, help='Show version')
@click.option('--no-banner', is_flag=True, help='Skip banner')
@click.pass_context
def app(ctx: click.Context, version: bool, no_banner: bool):
  """
  Nexe CLI Central - Nexe 0.8.5 Module Orchestrator

  \b
  Core commands:
   go       Start complete system (Server + embedded Qdrant)
   stop     Stop all Nexe services
   status   System status
   modules  List available CLI modules

  \b
  Module commands:
   chat     Interactive chat with Nexe
   memory   Memory management and data ingestion
   rag      RAG engine and vector management
   model    AI model management (download, list)
   ollama   Local LLM management with Ollama

  \b
  Examples:
   nexe go
   nexe chat
   nexe chat --rag
   nexe memory store "data"
   nexe model list
  """
  ctx.ensure_object(dict)
  ctx.obj['config'] = NexeConfig()
  ctx.obj['no_banner'] = no_banner

  if version:
    click.echo("Nexe CLI v1.0.0")
    ctx.exit(0)

  if ctx.invoked_subcommand is None:
    if not no_banner:
      print_banner()
    click.echo(ctx.get_help())

@app.command()
@click.option('--json', 'as_json', is_flag=True, help='Output JSON')
@click.pass_context
def modules(ctx: click.Context, as_json: bool):
  """List available CLI modules."""
  router = CLIRouter()
  clis = router.discover_all()

  if as_json:
    import json
    data = {
      "total": len(clis),
      "clis": [cli.to_dict() for cli in clis]
    }
    click.echo(json.dumps(data, indent=2))
  else:
    print_modules_table(clis)

def _start_nexe(ctx: click.Context):
  """Shared logic to start Nexe."""
  import os
  import subprocess
  from pathlib import Path

  project_root = Path(__file__).parent.parent.parent
  
  click.echo("Starting Nexe Server...")
  try:
    result = subprocess.run(
      [sys.executable, "-m", "core.app"],
      cwd=str(project_root),
      env={**os.environ, "PYTHONPATH": str(project_root)}
    )
    ctx.exit(result.returncode)
  except KeyboardInterrupt:
    click.echo("\n👋 Stopping...")
    ctx.exit(0)

@app.command()
@click.pass_context
def go(ctx: click.Context):
  """Start the full Nexe system (Server with embedded Qdrant)."""
  _start_nexe(ctx)

@app.command(name="go!")
@click.pass_context
def go_bang(ctx: click.Context):
  """Start the full Nexe system (Server with embedded Qdrant). Alias for 'go'."""
  _start_nexe(ctx)

@app.command()
@click.option('--force', '-f', is_flag=True, help='Skip confirmation')
@click.pass_context
def stop(ctx: click.Context, force: bool):
  """Stop all Nexe services (server)."""
  import os
  import signal

  services = [
    ("Nexe Server", "uvicorn.*nexe"),
  ]

  found = []
  for name, pattern in services:
    try:
      import subprocess
      result = subprocess.run(
        ["pgrep", "-f", pattern],
        capture_output=True, text=True
      )
      pids = [int(p) for p in result.stdout.strip().split('\n') if p.strip()]
      if pids:
        found.append((name, pattern, pids))
    except Exception:
      pass

  if not found:
    click.echo("ℹ️  No Nexe services are running.")
    return

  click.echo("Detected services:")
  for name, _, pids in found:
    click.echo(f"  - {name} (PID: {', '.join(str(p) for p in pids)})")

  if not force:
    if not click.confirm("\nStop all services?", default=True):
      click.echo("Cancelled.")
      return

  for name, _, pids in found:
    for pid in pids:
      try:
        os.kill(pid, signal.SIGTERM)
        click.echo(f"  ✓ {name} stopped (PID {pid})")
      except ProcessLookupError:
        click.echo(f"  - {name} no longer exists (PID {pid})")
      except PermissionError:
        click.echo(f"  ✗ {name} — permission denied (PID {pid})")

  click.echo("\n✅ Services stopped.")

@app.command()
@click.option('--json', 'as_json', is_flag=True, help='Output JSON')
@click.pass_context
def health(ctx: click.Context, as_json: bool):
  """Check server health via GET /health."""
  from .client import NexeClient

  config: NexeConfig = ctx.obj.get('config', NexeConfig())
  client = NexeClient(config)

  data = client.get_health()

  if as_json:
    import json
    click.echo(json.dumps(data, indent=2, default=str))
  else:
    if data.get("error"):
      click.echo(click.style(f"✗ Server offline: {data.get('message', 'unreachable')}", fg="red"))
    elif data.get("status") == "healthy":
      click.echo(click.style("✓ Server is healthy", fg="green"))
    else:
      click.echo(click.style(f"⚠ Server status: {data.get('status', 'unknown')}", fg="yellow"))

@app.command()
@click.option('--json', 'as_json', is_flag=True, help='Output JSON')
@click.pass_context
def status(ctx: click.Context, as_json: bool):
  """Show Nexe system status."""
  from .client import NexeClient

  config: NexeConfig = ctx.obj.get('config', NexeConfig())
  client = NexeClient(config)

  status_data = client.get_status()

  if as_json:
    import json
    click.echo(json.dumps(status_data, indent=2, default=str))
  else:
    print_status(status_data)

@app.command(name="setup-models")
@click.option('--apply', is_flag=True, help='Apply recommended changes to server.toml')
@click.pass_context
def setup_models(ctx: click.Context, apply: bool):
    """Detect hardware and configure recommended models."""
    from personality.models import ModelSelector
    from pathlib import Path
    import toml
    
    click.echo("Analyzing hardware...")
    selector = ModelSelector()
    hw_info = selector.analyze()
    click.echo(f"  - System: {hw_info.system} {hw_info.machine}")
    click.echo(f"  - CPU: {hw_info.processor}")
    click.echo(f"  - Available RAM: {hw_info.total_ram_gb} GB")
    click.echo(f"  - Apple Silicon: {'✅' if hw_info.is_apple_silicon else '❌'}")
    
    profile = selector.recommend()
    click.echo(f"\n🔍 Recommended Profile: {profile.tier.value.upper()}")
    click.echo(f"  - Engine: {profile.preferred_engine.value}")
    click.echo(f"  - Primary: {profile.primary_model}")
    click.echo(f"  - Secondary: {profile.secondary_model}")
    click.echo(f"  - Embedding: {profile.embedding_model}")
    click.echo(f"  - Context: {profile.context_window} tokens")
    click.echo(f"\n📝 Description: {profile.description}")
    
    if apply:
        config_path = Path("personality/server.toml")
        if not config_path.exists():
            click.echo("Error: server.toml not found!", err=True)
            return
            
        try:
            config = toml.load(config_path)
            new_config = selector.apply_to_config(config, profile)
            
            with open(config_path, 'w') as f:
                toml.dump(new_config, f)
            
            click.echo("\n✅ Configuration successfully applied to server.toml")
            
            # --- Auto-Download Logic ---
            if profile.preferred_engine.value == "mlx" and profile.mlx_model_id:
                click.echo(f"\n{click.style('Plug & Play: Downloading MLX model...', fg='cyan', bold=True)}")
                click.echo(f"   Model ID: {profile.mlx_model_id}")
                click.echo("   This may take a few minutes depending on your connection. Please wait...")
                
                # Check for huggingface-cli
                import shutil
                import subprocess
                
                # Download to storage/models to keep it locally managed
                # By default mlx-lm uses ~/.cache/huggingface.
                # For consistency with mlx_module (which requires a local path), we download to a local repo or use the default path.
                # For simplicity and robustness: use the mlx_lm library directly if installed for snapshot.
                
                try:
                    # Alternativa: Use huggingface_hub snapshot_download
                    from huggingface_hub import snapshot_download
                    local_dir = Path("storage/models") / profile.mlx_model_id.split("/")[-1]
                    click.echo(f"   Destination: {local_dir}")

                    snapshot_download(
                        repo_id=profile.mlx_model_id,
                        local_dir=local_dir,
                        local_dir_use_symlinks=False
                    )

                    # Update config with LOCAL absolute path (CRITICAL for mlx_module validation)
                    # Re-load, update, re-save
                    new_config['plugins']['models']['primary'] = str(local_dir.absolute())
                    with open(config_path, 'w') as f:
                        toml.dump(new_config, f)
                    click.echo(f"   Local path updated in server.toml: {local_dir}")
                    
                    click.echo(f"\n✅ {click.style('Model downloaded and configured!', fg='green')}")
                    
                except ImportError:
                     click.echo(click.style("   ⚠️ huggingface_hub not installed. Cannot auto-download.", fg="yellow"))
                     click.echo(f"   Run: pip install huggingface_hub")
                except Exception as e:
                     click.echo(click.style(f"   ❌ Error downloading model: {e}", fg="red"))
            
            elif profile.preferred_engine.value == "ollama":
                click.echo(f"\nℹ️  For Ollama, run manually: ollama pull {profile.primary_model}")

            click.echo("\nRestart the server to apply changes: ./nexe go")
            
        except Exception as e:
            click.echo(f"Error saving config: {e}", err=True)
    else:
        click.echo("\n💡 Run with --apply to save changes.")

def main():
  """Entry point for CLI."""
  try:
    app(standalone_mode=False)
  except click.ClickException as e:
    e.show()
    sys.exit(e.exit_code)
  except click.Abort:
    click.echo("\nAborted.", err=True)
    sys.exit(1)
  except KeyboardInterrupt:
    click.echo("\nInterrupted.", err=True)
    sys.exit(130)
  except SystemExit:
    raise
  except Exception as e:
    print_error(f"Unexpected error: {e}")
    sys.exit(1)

@app.group()
def model():
    """AI Model management (Download, List)."""
    pass

@model.command(name="list")
def list_models():
    """List verified models available for installation."""
    from personality.models.registry import list_models_table
    click.echo(f"\n{click.style('📦 AVAILABLE MODELS (Verified by Nexe)', bold=True, fg='cyan')}")
    click.echo("Use 'nexe model install <name>' to download one.\n")
    click.echo(list_models_table())
    click.echo()

@model.command(name="install")
@click.argument("name")
@click.option("--engine", "-e", type=click.Choice(['mlx', 'ollama']), default=None, help="Force engine")
def install_model(name: str, engine: Optional[str]):
    """
    Install a model by its short name (e.g. 'llama3.1-8b').

    Example: ./nexe model install gemma2b
    """
    from personality.models.registry import get_model_entry
    from pathlib import Path
    import toml
    
    # 1. Resolve model
    entry = get_model_entry(name)
    if not entry:
        click.echo(click.style(f"❌ Model '{name}' not found in registry.", fg="red"))
        click.echo("Run './nexe model list' to see available models.")
        return

    # 2. Detect Engine if not specified
    if not engine:
        # Check configure preferred engine
        config_path = Path("personality/server.toml")
        if config_path.exists():
             config = toml.load(config_path)
             engine = config.get("plugins", {}).get("models", {}).get("preferred_engine", "ollama")
             if engine == "auto": engine = "ollama" # Default safe
        else:
             engine = "ollama"
    
    click.echo(f"💿 Installing {click.style(entry.short_name, bold=True)} ({entry.size_gb}GB) for engine {click.style(engine.upper(), fg='yellow')}...")
    
    if engine == "mlx":
        # MLX Download Logic
        try:
            from huggingface_hub import snapshot_download
            repo_id = entry.mlx_hf_id
            local_dir = Path("storage/models") / repo_id.split("/")[-1]
            
            click.echo(f"   Source: {repo_id}")
            click.echo(f"   Destination: {local_dir}")
            
            snapshot_download(
                repo_id=repo_id,
                local_dir=local_dir,
                local_dir_use_symlinks=False
            )
            
            click.echo(f"\n✅ {click.style('Model downloaded!', fg='green')}")
            
            # Ask to set as primary
            if click.confirm("Set as primary model?"):
                config_path = Path("personality/server.toml")
                config = toml.load(config_path)
                config['plugins']['models']['primary'] = str(local_dir.absolute())
                with open(config_path, 'w') as f:
                    toml.dump(config, f)
                click.echo("   Configuration updated.")

        except ImportError:
             click.echo(click.style("⚠️ Error: huggingface_hub not installed.", fg="red"))
        except Exception as e:
             click.echo(click.style(f"❌ Error downloading: {e}", fg="red"))

    elif engine == "ollama":
        # Ollama Pull 
        import subprocess
        tag = entry.ollama_tag
        click.echo(f"   Running: ollama pull {tag}")
        try:
            subprocess.run(["ollama", "pull", tag], check=True)
            click.echo(f"\n✅ {click.style('Model downloaded to Ollama!', fg='green')}")

             # Ask to set as primary
            if click.confirm("Set as primary model?"):
                config_path = Path("personality/server.toml")
                config = toml.load(config_path)
                config['plugins']['models']['primary'] = tag
                with open(config_path, 'w') as f:
                    toml.dump(config, f)
                click.echo("   Configuration updated.")
                
        except Exception as e:
            click.echo(click.style(f"❌ Error en ollama pull: {e}", fg="red"))

    else:
        click.echo("Engine not supported for auto-install yet.")

@app.group()
def knowledge():
    """RAG document management (knowledge/)."""
    pass

@knowledge.command(name="ingest")
def ingest_knowledge_cmd():
    """Ingest documents from knowledge/ into Qdrant."""
    import asyncio
    import os
    from pathlib import Path

    project_root = Path(__file__).parent.parent.parent
    knowledge_path = project_root / "knowledge"
    _nexe_lang = os.getenv("NEXE_LANG", "ca")
    lang_path = knowledge_path / _nexe_lang
    if lang_path.is_dir():
        knowledge_path = lang_path

    if not knowledge_path.exists():
        click.echo(click.style(f"❌ Folder '{knowledge_path}' does not exist.", fg="red"))
        return

    # Check for files
    from core.ingest.ingest_knowledge import SUPPORTED_EXTENSIONS
    files = []
    for ext in SUPPORTED_EXTENSIONS:
        files.extend(knowledge_path.glob(f"**/*{ext}"))
    files.extend(knowledge_path.glob("**/*.pdf"))
    files = [f for f in files if not f.name.startswith('.')]

    if not files:
        click.echo(click.style("ℹ️  No documents found in knowledge/", fg="yellow"))
        click.echo("   Supported formats: .txt, .md, .pdf")
        click.echo(f"   Add documents: cp file.pdf {knowledge_path}/")
        return

    click.echo(f"📚 Ingesting {len(files)} document(s)...")

    from core.ingest.ingest_knowledge import ingest_knowledge
    success = asyncio.run(ingest_knowledge(knowledge_path, quiet=False))

    if success:
        click.echo(click.style("✅ Ingestion complete!", fg="green"))
    else:
        click.echo(click.style("⚠️  Ingestion completed with errors", fg="yellow"))

@knowledge.command(name="status")
def knowledge_status():
    """Show status of the user_knowledge collection."""
    import asyncio

    async def check_status():
        try:
            from memory.memory.api import MemoryAPI
            memory = MemoryAPI()
            await memory.initialize()

            if await memory.collection_exists("user_knowledge"):
                count = await memory.count("user_knowledge")
                click.echo(f"📊 Collection 'user_knowledge':")
                click.echo(f"   - Documents: {count} fragments")
                click.echo(f"   - Status: ✅ Active")
            else:
                click.echo(click.style("ℹ️  Collection 'user_knowledge' does not exist.", fg="yellow"))
                click.echo("   Run: ./nexe knowledge ingest")

            await memory.close()
        except Exception as e:
            click.echo(click.style(f"❌ Error connecting to Qdrant: {e}", fg="red"))
            click.echo("   Make sure the server is running: ./nexe go")

    asyncio.run(check_status())

# Register encryption subcommands
try:
    from core.crypto.cli import encryption
    app.add_command(encryption)
except ImportError:
    pass

if __name__ == "__main__":
  main()