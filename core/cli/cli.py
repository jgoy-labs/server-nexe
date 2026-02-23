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

class DynamicGroup(click.Group):
  """
  Click Group que intercepta comandos no definits i els redirigeix
  al router per invocar CLIs de mòduls via subprocess.
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
      """Comando dinàmic que delega al CLI del mòdul."""
      all_args = list(extra_args) + list(args)

      exit_code = self._router.execute(cmd_name, all_args)
      ctx.exit(exit_code)

    dynamic_cmd.help = cli_info.description

    return dynamic_cmd

  def list_commands(self, ctx: click.Context) -> List[str]:
    """Retorna tots els comandos disponibles (built-in + mòduls)."""
    builtin = super().list_commands(ctx)

    module_clis = [cli.alias for cli in self._router.discover_all()]

    return sorted(set(builtin + module_clis))

@click.group(cls=DynamicGroup, invoke_without_command=True)
@click.option('--version', '-V', is_flag=True, help='Show version')
@click.option('--no-banner', is_flag=True, help='Skip banner')
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
  """Llistar mòduls amb CLI disponibles."""
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
  """Lògica comuna per arrencar Nexe."""
  import os
  import subprocess
  from pathlib import Path

  project_root = Path(__file__).parent.parent.parent
  
  click.echo("Arrencant Nexe Server...")
  try:
    result = subprocess.run(
      [sys.executable, "-m", "core.app"],
      cwd=str(project_root),
      env={**os.environ, "PYTHONPATH": str(project_root)}
    )
    ctx.exit(result.returncode)
  except KeyboardInterrupt:
    click.echo("\n👋 Aturant...")
    ctx.exit(0)

@app.command()
@click.pass_context
def go(ctx: click.Context):
  """Arrencar el sistema Nexe complet (Qdrant + Servidor)."""
  _start_nexe(ctx)

@app.command(name="go!")
@click.pass_context
def go_bang(ctx: click.Context):
  """Arrencar el sistema Nexe complet (Qdrant + Servidor). Alias de 'go'."""
  _start_nexe(ctx)

@app.command()
@click.option('--json', 'as_json', is_flag=True, help='Output JSON')
@click.pass_context
def status(ctx: click.Context, as_json: bool):
  """Mostrar estat del sistema Nexe."""
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
    """Detecta maquinari i configura els models recomanats."""
    from personality.models import ModelSelector
    from pathlib import Path
    import toml
    
    click.echo("Analitzant maquinari...")
    selector = ModelSelector()
    hw_info = selector.analyze()
    click.echo(f"  - Sistema: {hw_info.system} {hw_info.machine}")
    click.echo(f"  - Processor: {hw_info.processor}")
    click.echo(f"  - RAM disponible: {hw_info.total_ram_gb} GB")
    click.echo(f"  - Apple Silicon: {'✅' if hw_info.is_apple_silicon else '❌'}")
    
    profile = selector.recommend()
    click.echo(f"\n🔍 Perfil Recomanat: {profile.tier.value.upper()}")
    click.echo(f"  - Engine: {profile.preferred_engine.value}")
    click.echo(f"  - Primary: {profile.primary_model}")
    click.echo(f"  - Secondary: {profile.secondary_model}")
    click.echo(f"  - Embedding: {profile.embedding_model}")
    click.echo(f"  - Context: {profile.context_window} tokens")
    click.echo(f"\n📝 Descripció: {profile.description}")
    
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
            
            click.echo("\n✅ Configuració aplicada correctament a server.toml")
            
            # --- Auto-Download Logic ---
            if profile.preferred_engine.value == "mlx" and profile.mlx_model_id:
                click.echo(f"\n{click.style('Plug & Play: Descarregant model MLX...', fg='cyan', bold=True)}")
                click.echo(f"   Model ID: {profile.mlx_model_id}")
                click.echo("   Això pot trigar uns minuts segons la teva connexió. Paciència...")
                
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
                    click.echo(f"   Destí: {local_dir}")
                    
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
                    click.echo(f"   Ruta local actualitzada a server.toml: {local_dir}")
                    
                    click.echo(f"\n✅ {click.style('Model descarregat i configurat!', fg='green')}")
                    
                except ImportError:
                     click.echo(click.style("   ⚠️ huggingface_hub not installed. Cannot auto-download.", fg="yellow"))
                     click.echo(f"   Run: pip install huggingface_hub")
                except Exception as e:
                     click.echo(click.style(f"   ❌ Error descarregant model: {e}", fg="red"))
            
            elif profile.preferred_engine.value == "ollama":
                click.echo(f"\nℹ️  Per Ollama, executa manualment: ollama pull {profile.primary_model}")

            click.echo("\nReinicia el servidor per aplicar canvis: ./nexe go")
            
        except Exception as e:
            click.echo(f"Error saving config: {e}", err=True)
    else:
        click.echo("\n💡 Executa amb --apply per guardar els canvis.")

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
    """Gestió de Models d'IA (Descarregar, Llistar)."""
    pass

@model.command(name="list")
def list_models():
    """Llista els models verificats disponibles per instal·lar."""
    from personality.models.registry import list_models_table
    click.echo(f"\n{click.style('📦 MODELS DISPONIBLES (Verificats per Nexe)', bold=True, fg='cyan')}")
    click.echo("Use 'nexe model install <nom>' per descarregar-ne un.\n")
    click.echo(list_models_table())
    click.echo()

@model.command(name="install")
@click.argument("name")
@click.option("--engine", "-e", type=click.Choice(['mlx', 'ollama']), default=None, help="Forçar motor")
def install_model(name: str, engine: Optional[str]):
    """
    Instal·la un model pel seu nom curt (ex: 'llama3.1-8b').
    
    Exemple: ./nexe model install gemma2b
    """
    from personality.models.registry import get_model_entry
    from pathlib import Path
    import toml
    
    # 1. Resolve model
    entry = get_model_entry(name)
    if not entry:
        click.echo(click.style(f"❌ Model '{name}' no trobat al registre.", fg="red"))
        click.echo("Executa './nexe model list' per veure'n la llista.")
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
    
    click.echo(f"💿 Instal·lant {click.style(entry.short_name, bold=True)} ({entry.size_gb}GB) per a motor {click.style(engine.upper(), fg='yellow')}...")
    
    if engine == "mlx":
        # MLX Download Logic
        try:
            from huggingface_hub import snapshot_download
            repo_id = entry.mlx_hf_id
            local_dir = Path("storage/models") / repo_id.split("/")[-1]
            
            click.echo(f"   Font: {repo_id}")
            click.echo(f"   Destí: {local_dir}")
            
            snapshot_download(
                repo_id=repo_id,
                local_dir=local_dir,
                local_dir_use_symlinks=False
            )
            
            click.echo(f"\n✅ {click.style('Model descarregat!', fg='green')}")
            
            # Ask to set as primary
            if click.confirm("Vols establir-lo com a model principal (Primary)?"):
                config_path = Path("personality/server.toml")
                config = toml.load(config_path)
                config['plugins']['models']['primary'] = str(local_dir.absolute())
                with open(config_path, 'w') as f:
                    toml.dump(config, f)
                click.echo("   Configuració actualitzada.")
                
        except ImportError:
             click.echo(click.style("⚠️ Error: huggingface_hub no instal·lat.", fg="red"))
        except Exception as e:
             click.echo(click.style(f"❌ Error descarregant: {e}", fg="red"))

    elif engine == "ollama":
        # Ollama Pull 
        import subprocess
        tag = entry.ollama_tag
        click.echo(f"   Executant: ollama pull {tag}")
        try:
            subprocess.run(["ollama", "pull", tag], check=True)
            click.echo(f"\n✅ {click.style('Model descarregat a Ollama!', fg='green')}")
            
             # Ask to set as primary
            if click.confirm("Vols establir-lo com a model principal (Primary)?"):
                config_path = Path("personality/server.toml")
                config = toml.load(config_path)
                config['plugins']['models']['primary'] = tag
                with open(config_path, 'w') as f:
                    toml.dump(config, f)
                click.echo("   Configuració actualitzada.")
                
        except Exception as e:
            click.echo(click.style(f"❌ Error en ollama pull: {e}", fg="red"))

    else:
        click.echo("Engine not supported for auto-install yet.")

@app.group()
def knowledge():
    """Gestió de documents RAG (knowledge/)."""
    pass

@knowledge.command(name="ingest")
def ingest_knowledge_cmd():
    """Ingereix els documents de knowledge/ a Qdrant."""
    import asyncio
    from pathlib import Path

    project_root = Path(__file__).parent.parent.parent
    knowledge_path = project_root / "knowledge"

    if not knowledge_path.exists():
        click.echo(click.style(f"❌ Carpeta '{knowledge_path}' no existeix.", fg="red"))
        return

    # Check for files
    from core.ingest.ingest_knowledge import SUPPORTED_EXTENSIONS
    files = []
    for ext in SUPPORTED_EXTENSIONS:
        files.extend(knowledge_path.glob(f"**/*{ext}"))
    files.extend(knowledge_path.glob("**/*.pdf"))
    files = [f for f in files if not f.name.startswith('.')]

    if not files:
        click.echo(click.style("ℹ️  No hi ha documents a knowledge/", fg="yellow"))
        click.echo("   Formats suportats: .txt, .md, .pdf")
        click.echo(f"   Afegeix documents: cp fitxer.pdf {knowledge_path}/")
        return

    click.echo(f"📚 Ingerint {len(files)} document(s)...")

    from core.ingest.ingest_knowledge import ingest_knowledge
    success = asyncio.run(ingest_knowledge(knowledge_path, quiet=False))

    if success:
        click.echo(click.style("✅ Ingesta completada!", fg="green"))
    else:
        click.echo(click.style("⚠️  Ingesta amb errors", fg="yellow"))

@knowledge.command(name="status")
def knowledge_status():
    """Mostra l'estat de la col·lecció user_knowledge."""
    import asyncio

    async def check_status():
        try:
            from memory.memory.api import MemoryAPI
            memory = MemoryAPI()
            await memory.initialize()

            if await memory.collection_exists("user_knowledge"):
                count = await memory.count("user_knowledge")
                click.echo(f"📊 Col·lecció 'user_knowledge':")
                click.echo(f"   - Documents: {count} fragments")
                click.echo(f"   - Estat: ✅ Activa")
            else:
                click.echo(click.style("ℹ️  Col·lecció 'user_knowledge' no existeix.", fg="yellow"))
                click.echo("   Executa: ./nexe knowledge ingest")

            await memory.close()
        except Exception as e:
            click.echo(click.style(f"❌ Error connectant amb Qdrant: {e}", fg="red"))
            click.echo("   Assegura't que el servidor està corrent: ./nexe go")

    asyncio.run(check_status())

if __name__ == "__main__":
  main()