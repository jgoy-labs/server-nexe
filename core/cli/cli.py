"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: core/cli/cli.py
Description: CLI Central Nexe 0.8 - Aplicació Click principal.

www.jgoy.net
────────────────────────────────────
"""

import sys
import click
from typing import Optional, List

from .router import CLIRouter
from .output import print_banner, print_modules_table, print_status, print_error
from .config import NexeConfig
from .i18n import t

class DynamicGroup(click.Group):
  """
  Click group that intercepts unknown commands and routes them
  to module CLIs via subprocess.
  """

  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self._router = CLIRouter()

  def get_command(self, ctx: click.Context, cmd_name: str) -> Optional[click.Command]:
    """
    Intenta trobar el comando:
    1. Primer busca en comandos registrats (modules, status, etc.)
    2. Si no el troba, busca en CLIs de mòduls
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
    """Return all available commands (built-in + modules)."""
    builtin = super().list_commands(ctx)

    module_clis = [cli.alias for cli in self._router.discover_all()]

    return sorted(set(builtin + module_clis))

@click.group(cls=DynamicGroup, invoke_without_command=True)
@click.option('--version', '-V', is_flag=True, help=t("cli.main.options.version", "Show version"))
@click.option('--no-banner', is_flag=True, help=t("cli.main.options.no_banner", "Skip banner"))
@click.pass_context
def app(ctx: click.Context, version: bool, no_banner: bool):
  """
  Nexe CLI Central - Nexe 0.8 Module Orchestrator

  \b
  Core commands:
   go       Start complete system (Qdrant + Server)
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
    click.echo(t("cli.main.version", "Nexe CLI v1.0.0"))
    ctx.exit(0)

  if ctx.invoked_subcommand is None:
    if not no_banner:
      print_banner()
    click.echo(ctx.get_help())

@app.command()
@click.option('--json', 'as_json', is_flag=True, help=t("cli.main.options.json", "Output JSON"))
@click.pass_context
def modules(ctx: click.Context, as_json: bool):
  """List modules with available CLIs."""
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
  """Common logic for starting Nexe."""
  import os
  import subprocess
  from pathlib import Path

  project_root = Path(__file__).parent.parent.parent
  
  click.echo(t("cli.main.starting_server", "Starting Nexe Server..."))
  try:
    result = subprocess.run(
      [sys.executable, "-m", "core.app"],
      cwd=str(project_root),
      env={**os.environ, "PYTHONPATH": str(project_root)}
    )
    ctx.exit(result.returncode)
  except KeyboardInterrupt:
    click.echo(t("cli.main.stopping", "\n👋 Stopping..."))
    ctx.exit(0)

@app.command()
@click.pass_context
def go(ctx: click.Context):
  """Start the complete Nexe system (Qdrant + Server)."""
  _start_nexe(ctx)

@app.command(name="go!")
@click.pass_context
def go_bang(ctx: click.Context):
  """Start the complete Nexe system (Qdrant + Server). Alias for 'go'."""
  _start_nexe(ctx)

@app.command()
@click.option('--json', 'as_json', is_flag=True, help=t("cli.main.options.json", "Output JSON"))
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
@click.option('--apply', is_flag=True, help=t("cli.main.setup_models.options.apply", "Apply recommended changes to server.toml"))
@click.pass_context
def setup_models(ctx: click.Context, apply: bool):
    """Detect hardware and configure recommended models."""
    from personality.models import ModelSelector
    from pathlib import Path
    import toml
    
    click.echo(t("cli.main.setup_models.analyzing_hw", "Analyzing hardware..."))
    selector = ModelSelector()
    hw_info = selector.analyze()
    click.echo(t(
        "cli.main.setup_models.hw.system",
        "  - System: {system} {machine}",
        system=hw_info.system,
        machine=hw_info.machine
    ))
    click.echo(t(
        "cli.main.setup_models.hw.processor",
        "  - Processor: {processor}",
        processor=hw_info.processor
    ))
    click.echo(t(
        "cli.main.setup_models.hw.ram",
        "  - Available RAM: {ram} GB",
        ram=hw_info.total_ram_gb
    ))
    click.echo(t(
        "cli.main.setup_models.hw.apple_silicon",
        "  - Apple Silicon: {status}",
        status="✅" if hw_info.is_apple_silicon else "❌"
    ))
    
    profile = selector.recommend()
    click.echo(t(
        "cli.main.setup_models.profile.title",
        "\n🔍 Recommended Profile: {tier}",
        tier=profile.tier.value.upper()
    ))
    click.echo(t(
        "cli.main.setup_models.profile.engine",
        "  - Engine: {engine}",
        engine=profile.preferred_engine.value
    ))
    click.echo(t(
        "cli.main.setup_models.profile.primary",
        "  - Primary: {model}",
        model=profile.primary_model
    ))
    click.echo(t(
        "cli.main.setup_models.profile.secondary",
        "  - Secondary: {model}",
        model=profile.secondary_model
    ))
    click.echo(t(
        "cli.main.setup_models.profile.embedding",
        "  - Embedding: {model}",
        model=profile.embedding_model
    ))
    click.echo(t(
        "cli.main.setup_models.profile.context",
        "  - Context: {tokens} tokens",
        tokens=profile.context_window
    ))
    click.echo(t(
        "cli.main.setup_models.profile.description",
        "\n📝 Description: {description}",
        description=profile.description
    ))
    
    if apply:
        config_path = Path("personality/server.toml")
        if not config_path.exists():
            click.echo(t("cli.main.setup_models.config_not_found", "Error: server.toml not found!"), err=True)
            return
            
        try:
            config = toml.load(config_path)
            new_config = selector.apply_to_config(config, profile)
            
            with open(config_path, 'w') as f:
                toml.dump(new_config, f)
            
            click.echo(t(
                "cli.main.setup_models.config_applied",
                "\n✅ Configuration applied to server.toml"
            ))
            
            # --- Auto-Download Logic ---
            if profile.preferred_engine.value == "mlx" and profile.mlx_model_id:
                click.echo(f"\n{click.style(t('cli.main.setup_models.mlx_downloading', 'Plug & Play: Downloading MLX model...'), fg='cyan', bold=True)}")
                click.echo(t("cli.main.setup_models.mlx_model_id", "   Model ID: {model_id}", model_id=profile.mlx_model_id))
                click.echo(t("cli.main.setup_models.mlx_wait", "   This may take a few minutes depending on your connection. Please wait..."))
                
                # Check for huggingface-cli
                import shutil
                import subprocess
                
                # Descarreguem a storage/models per tenir-ho controlat localment
                # Però mlx-lm per defecte usa ~/.cache/huggingface.
                # Per ser consistent amb mlx_module (que vol path local), fem download a repositori local o usem path per defecte.
                # Per simplicitat i robustesa ara: usem la llibreria mlx_lm directament si està instal·lada per fer snapshot.
                
                try:
                    # Alternativa: Use huggingface_hub snapshot_download
                    from huggingface_hub import snapshot_download
                    local_dir = Path("storage/models") / profile.mlx_model_id.split("/")[-1]
                    click.echo(t("cli.main.setup_models.mlx_destination", "   Destination: {path}", path=local_dir))
                    
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
                    click.echo(t("cli.main.setup_models.mlx_local_path_updated", "   Local path updated in server.toml: {path}", path=local_dir))
                    
                    click.echo(f"\n✅ {click.style(t('cli.main.setup_models.mlx_downloaded', 'Model downloaded and configured!'), fg='green')}")
                    
                except ImportError:
                    click.echo(click.style(t("cli.main.setup_models.hf_missing", "   ⚠️ huggingface_hub not installed. Cannot auto-download."), fg="yellow"))
                    click.echo(t("cli.main.setup_models.hf_install", "   Run: pip install huggingface_hub"))
                except Exception as e:
                    click.echo(click.style(t("cli.main.setup_models.hf_error", "   ❌ Error downloading model: {error}", error=str(e)), fg="red"))
            
            elif profile.preferred_engine.value == "ollama":
                click.echo(t("cli.main.setup_models.ollama_hint", "\nℹ️  For Ollama, run manually: ollama pull {model}", model=profile.primary_model))

            click.echo(t("cli.main.setup_models.restart_hint", "\nRestart the server to apply changes: ./nexe go"))
            
        except Exception as e:
            click.echo(t("cli.main.setup_models.save_error", "Error saving config: {error}", error=str(e)), err=True)
    else:
        click.echo(t("cli.main.setup_models.apply_hint", "\n💡 Run with --apply to save changes."))

def main():
  """Entry point for CLI."""
  try:
    app(standalone_mode=False)
  except click.ClickException as e:
    e.show()
    sys.exit(e.exit_code)
  except click.Abort:
    click.echo(t("cli.main.aborted", "\nAborted."), err=True)
    sys.exit(1)
  except KeyboardInterrupt:
    click.echo(t("cli.main.interrupted", "\nInterrupted."), err=True)
    sys.exit(130)
  except SystemExit:
    raise
  except Exception as e:
    print_error(t("cli.main.unexpected_error", "Unexpected error: {error}", error=str(e)))
    sys.exit(1)

@app.group()
def model():
    """AI model management (download, list)."""
    pass

@model.command(name="list")
def list_models():
    """List verified models available for install."""
    from personality.models.registry import list_models_table
    click.echo(f"\n{click.style(t('cli.main.models.available_title', '📦 AVAILABLE MODELS (Verified by Nexe)'), bold=True, fg='cyan')}")
    click.echo(t("cli.main.models.install_hint", "Use 'nexe model install <name>' to download one.\n"))
    click.echo(list_models_table())
    click.echo()

@model.command(name="install")
@click.argument("name")
@click.option("--engine", "-e", type=click.Choice(['mlx', 'ollama']), default=None,
              help=t("cli.main.models.options.force_engine", "Force engine"))
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
        click.echo(click.style(
            t("cli.main.models.not_found", "❌ Model '{name}' not found in registry.", name=name),
            fg="red"
        ))
        click.echo(t("cli.main.models.list_hint", "Run './nexe model list' to see the list."))
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
    
    click.echo(
        t(
            "cli.main.models.installing",
            "💿 Installing {model} ({size}GB) for engine {engine}...",
            model=click.style(entry.short_name, bold=True),
            size=entry.size_gb,
            engine=click.style(engine.upper(), fg='yellow')
        )
    )
    
    if engine == "mlx":
        # MLX Download Logic
        try:
            from huggingface_hub import snapshot_download
            repo_id = entry.mlx_hf_id
            local_dir = Path("storage/models") / repo_id.split("/")[-1]
            
            click.echo(t("cli.main.models.source", "   Source: {source}", source=repo_id))
            click.echo(t("cli.main.models.destination", "   Destination: {path}", path=local_dir))
            
            snapshot_download(
                repo_id=repo_id,
                local_dir=local_dir,
                local_dir_use_symlinks=False
            )
            
            click.echo(f"\n✅ {click.style(t('cli.main.models.downloaded', 'Model downloaded!'), fg='green')}")
            
            # Ask to set as primary
            if click.confirm(t("cli.main.models.set_primary_prompt", "Set as primary model?")):
                config_path = Path("personality/server.toml")
                config = toml.load(config_path)
                config['plugins']['models']['primary'] = str(local_dir.absolute())
                with open(config_path, 'w') as f:
                    toml.dump(config, f)
                click.echo(t("cli.main.models.config_updated", "   Configuration updated."))
                
        except ImportError:
             click.echo(click.style(t("cli.main.models.hf_missing", "⚠️ Error: huggingface_hub not installed."), fg="red"))
        except Exception as e:
             click.echo(click.style(t("cli.main.models.download_error", "❌ Download error: {error}", error=str(e)), fg="red"))

    elif engine == "ollama":
        # Ollama Pull 
        import subprocess
        tag = entry.ollama_tag
        click.echo(t("cli.main.models.ollama_running", "   Running: ollama pull {tag}", tag=tag))
        try:
            subprocess.run(["ollama", "pull", tag], check=True)
            click.echo(f"\n✅ {click.style(t('cli.main.models.ollama_downloaded', 'Model downloaded to Ollama!'), fg='green')}")
            
             # Ask to set as primary
            if click.confirm(t("cli.main.models.set_primary_prompt", "Set as primary model?")):
                config_path = Path("personality/server.toml")
                config = toml.load(config_path)
                config['plugins']['models']['primary'] = tag
                with open(config_path, 'w') as f:
                    toml.dump(config, f)
                click.echo(t("cli.main.models.config_updated", "   Configuration updated."))
                
        except Exception as e:
            click.echo(click.style(t("cli.main.models.ollama_error", "❌ Error running ollama pull: {error}", error=str(e)), fg="red"))

    else:
        click.echo(t("cli.main.models.engine_not_supported", "Engine not supported for auto-install yet."))

@app.group()
def knowledge():
    """RAG document management (knowledge/)."""
    pass

@knowledge.command(name="ingest")
def ingest_knowledge_cmd():
    """Ingest documents from knowledge/ into Qdrant."""
    import asyncio
    from pathlib import Path

    project_root = Path(__file__).parent.parent.parent
    knowledge_path = project_root / "knowledge"

    if not knowledge_path.exists():
        click.echo(click.style(
            t("cli.main.knowledge.dir_not_found", "❌ Folder '{path}' does not exist.", path=knowledge_path),
            fg="red"
        ))
        return

    # Check for files
    from core.ingest.ingest_knowledge import SUPPORTED_EXTENSIONS
    files = []
    for ext in SUPPORTED_EXTENSIONS:
        files.extend(knowledge_path.glob(f"**/*{ext}"))
    files.extend(knowledge_path.glob("**/*.pdf"))
    files = [f for f in files if not f.name.startswith('.') and f.name != 'README.md']

    if not files:
        click.echo(click.style(
            t("cli.main.knowledge.no_docs", "ℹ️  No documents found in knowledge/"),
            fg="yellow"
        ))
        click.echo(t("cli.main.knowledge.supported_formats", "   Supported formats: .txt, .md, .pdf"))
        click.echo(t("cli.main.knowledge.add_docs", "   Add documents: cp file.pdf {path}/", path=knowledge_path))
        return

    click.echo(t("cli.main.knowledge.ingesting", "📚 Ingesting {count} document(s)...", count=len(files)))

    from core.ingest.ingest_knowledge import ingest_knowledge
    success = asyncio.run(ingest_knowledge(knowledge_path, quiet=False))

    if success:
        click.echo(click.style(t("cli.main.knowledge.ingest_done", "✅ Ingestion completed!"), fg="green"))
    else:
        click.echo(click.style(t("cli.main.knowledge.ingest_warn", "⚠️  Ingestion with warnings"), fg="yellow"))

@knowledge.command(name="status")
def knowledge_status():
    """Show status for the user_knowledge collection."""
    import asyncio

    async def check_status():
        try:
            from memory.memory.api import MemoryAPI
            memory = MemoryAPI()
            await memory.initialize()

            if await memory.collection_exists("user_knowledge"):
                count = await memory.count("user_knowledge")
                click.echo(t("cli.main.knowledge.status_title", "📊 Collection 'user_knowledge':"))
                click.echo(t("cli.main.knowledge.status_docs", "   - Documents: {count} fragments", count=count))
                click.echo(t("cli.main.knowledge.status_state", "   - Status: ✅ Active"))
            else:
                click.echo(click.style(
                    t("cli.main.knowledge.collection_missing", "ℹ️  Collection 'user_knowledge' does not exist."),
                    fg="yellow"
                ))
                click.echo(t("cli.main.knowledge.ingest_hint", "   Run: ./nexe knowledge ingest"))

            await memory.close()
        except Exception as e:
            click.echo(click.style(
                t("cli.main.knowledge.qdrant_error", "❌ Error connecting to Qdrant: {error}", error=str(e)),
                fg="red"
            ))
            click.echo(t("cli.main.knowledge.server_hint", "   Make sure the server is running: ./nexe go"))

    asyncio.run(check_status())

if __name__ == "__main__":
  main()
