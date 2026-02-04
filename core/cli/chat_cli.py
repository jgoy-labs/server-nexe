"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: core/cli/chat_cli.py
Description: CLI de Chat unificat. Detecta motor disponible (MLX, Llama.cpp, Ollama)
             i proporciona una interfície interactiva simple.

www.jgoy.net
────────────────────────────────────
"""

import sys
import logging
import asyncio
import click
from pathlib import Path
from typing import Optional, List, Dict

logger = logging.getLogger(__name__)

# Helpers per detecció de motors
def get_default_system_prompt():
    """Llegeix el system prompt des de personality/server.toml si existeix."""
    import os
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib
    
    config_path = Path(__file__).parent.parent.parent / "personality" / "server.toml"
    if config_path.exists():
        try:
            with open(config_path, "rb") as f:
                data = tomllib.load(f)
                return data.get("personality", {}).get("prompt", {}).get("system_prompt")
        except Exception as e:
            logger.debug("Failed to load system prompt: %s", e)
    return "Ets Nexe, un assistent d'IA local, precís i segur."

def detect_engine():
    """
    Detecta quin motor està configurat/disponible.

    Prioritat:
    1. NEXE_MODEL_ENGINE (configurat per l'instal·lador al .env)
    2. server.toml preferred_engine
    3. Detecció per variables de model específiques
    4. Fallback a ollama
    """
    import os
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib

    # IMPORTANT: Carregar .env ABANS de llegir variables d'entorn
    from dotenv import load_dotenv
    project_root = Path(__file__).parent.parent.parent
    env_path = project_root / ".env"
    if env_path.exists():
        load_dotenv(env_path)

    # 1. PRIORITAT MÀXIMA: Variable d'entorn del instal·lador
    env_engine = os.getenv("NEXE_MODEL_ENGINE")
    if env_engine and env_engine.lower() not in ("auto", ""):
        return env_engine.lower()

    # 2. Intentar llegir des de server.toml
    config_path = Path(__file__).parent.parent.parent / "personality" / "server.toml"
    if config_path.exists():
        try:
            with open(config_path, "rb") as f:
                data = tomllib.load(f)
                engine = data.get("plugins", {}).get("models", {}).get("preferred_engine", "auto")
                if engine != "auto":
                    return engine
        except Exception as e:
            logger.debug("Failed to read engine config: %s", e)

    # 3. Fallback a variables d'entorn de models específics
    if os.getenv("NEXE_MLX_MODEL"):
        return "mlx"
    if os.getenv("NEXE_LLAMA_CPP_MODEL"):
        return "llama_cpp"

    # 4. Fallback final (default)
    return "ollama"

async def get_response_stream(engine: str, prompt: str, system: str, history: List[Dict], use_rag: bool):
    """Obté resposta en streaming segons el motor."""
    # Nota: Aquí es faria el dispatch real cap als mòduls. 
    # Per simplicitat en CLI, fem una crida a l'API local si el server està up,
    # o instanciem el node directament si volem "offline chat".
    
    # En aquesta fase, deleguem al mòdul corresponent si està carregat.
    pass

@click.command()
@click.option('--engine', '-e', type=click.Choice(['mlx', 'llama_cpp', 'ollama']), help='Motor d\'inferència')
@click.option('--system', '-s', default=None, help='System prompt / Identitat')
@click.option('--no-rag', is_flag=True, help='Desactivar context de memòria (RAG)')
@click.option('--model', '-m', help='Nom del model (per Ollama)')
def chat(engine: Optional[str], system: Optional[str], no_rag: bool, model: Optional[str]):
    """
    Inicia un xat interactiu amb Nexe.
    Detecta automàticament el motor configurat si no s'especifica.
    """
    asyncio.run(_chat_async(engine, system, no_rag, model))

def detect_model():
    """Detecta quin model està configurat."""
    import os
    from dotenv import load_dotenv

    # Load .env
    project_root = Path(__file__).parent.parent.parent
    env_path = project_root / ".env"
    if env_path.exists():
        load_dotenv(env_path)

    # Get model from env
    model_name = os.getenv("NEXE_DEFAULT_MODEL")
    if model_name:
        # Simplify display name (remove long prefixes)
        if "/" in model_name:
            model_name = model_name.split("/")[-1]
        return model_name

    return "auto"


async def _chat_async(engine: Optional[str], system: Optional[str], no_rag: bool, model: Optional[str]):
    from .utils.api_client import NexeAPIClient

    rag = not no_rag

    if not engine:
        engine = detect_engine()

    # Detect model if not specified
    if not model:
        model = detect_model()

    if not system:
        system = get_default_system_prompt()

    client = NexeAPIClient()

    # Check server status
    if not await client.is_server_running():
        click.echo(click.style("\n❌ Error: El servidor Nexe no respon a http://127.0.0.1:9119", fg="red", bold=True))
        click.echo("Assegura't que has executat './nexe go' en una altra terminal abans d'iniciar el xat.\n")
        return

    # Get actual engine from server status (not just from .env)
    try:
        import httpx
        async with httpx.AsyncClient() as http_client:
            response = await http_client.get("http://127.0.0.1:9119/status", timeout=5.0)
            if response.status_code == 200:
                status = response.json()
                actual_engine = status.get("engine", engine)
                if actual_engine != engine:
                    # Server is using different engine than .env (e.g., fallback to Ollama)
                    engine = f"{actual_engine} (fallback)"
    except Exception:
        # If status check fails, use .env engine
        pass

    click.echo(f"\n  {click.style('🚀 Nexe Chat', fg='cyan', bold=True)}")
    click.echo(f"  {click.style('Engine:', fg='yellow')} {engine}  |  {click.style('Model:', fg='yellow')} {model}  |  {click.style('RAG:', fg='yellow')} {'✅ On' if rag else '❌ Off'}")
    click.echo(click.style('  ─────────────────────────────────────────', dim=True))
    click.echo(click.style('  Commands: /save <text> · /recall <query> · /context on|off · /help', dim=True))
    click.echo(click.style('  Type "exit" or Ctrl+C to quit', dim=True) + "\n")

    history = []
    if system:
        history.append({"role": "system", "content": system})
    
    while True:
        try:
            user_input = click.prompt(click.style("Tu", fg="green", bold=True))

            if user_input.lower() in ["sortir", "exit", "quit", "q"]:
                break

            if user_input.lower() == "clear":
                history = [h for h in history if h["role"] == "system"]
                click.echo("🧹 Historial netejat.")
                continue

            # Slash commands
            if user_input.startswith("/"):
                cmd_parts = user_input[1:].split(" ", 1)
                cmd = cmd_parts[0].lower()
                cmd_arg = cmd_parts[1] if len(cmd_parts) > 1 else ""

                if cmd == "save" and cmd_arg:
                    # Save to memory via API and get AI acknowledgment
                    try:
                        success = await client.memory_store(cmd_arg)
                        if success:
                            # Ask AI to acknowledge what was saved
                            ack_prompt = f"L'usuari acaba de dir-te que recordis això: \"{cmd_arg}\". Respon breument confirmant que ho recordaràs, sense repetir tota la informació."
                            history.append({"role": "user", "content": ack_prompt})

                            click.echo(click.style("Nexe: ", fg="cyan", bold=True), nl=False)
                            full_response = ""
                            async for chunk in client.chat_stream(messages=history, engine=engine, rag=False):
                                print(chunk, end="", flush=True)
                                full_response += chunk
                            print()

                            # Replace the ack_prompt with original save content in history
                            history[-1] = {"role": "user", "content": f"[Guardat a memòria: {cmd_arg}]"}
                            history.append({"role": "assistant", "content": full_response})
                        else:
                            click.echo(click.style("❌ Error guardant.", fg="red"))
                    except Exception as e:
                        click.echo(click.style(f"❌ Error: {e}", fg="red"))
                    continue

                elif cmd == "recall" and cmd_arg:
                    # Search memory
                    try:
                        results = await client.memory_search(cmd_arg)
                        if results:
                            click.echo(click.style("📚 Trobat a memòria:", fg="cyan"))
                            for r in results[:3]:
                                click.echo(f"  • {r.get('content', r)[:100]}...")
                        else:
                            click.echo(click.style("🔍 No s'ha trobat res.", dim=True))
                    except Exception as e:
                        click.echo(click.style(f"❌ Error: {e}", fg="red"))
                    continue

                elif cmd == "context":
                    if cmd_arg.lower() == "off":
                        rag = False
                        click.echo(click.style("🔕 Context RAG desactivat.", fg="yellow"))
                    elif cmd_arg.lower() == "on":
                        rag = True
                        click.echo(click.style("🔔 Context RAG activat.", fg="green"))
                    else:
                        click.echo(f"RAG: {'✅ Actiu' if rag else '❌ Inactiu'}")
                    continue

                elif cmd == "help":
                    click.echo(click.style("\n📖 Comandes disponibles:", fg="cyan", bold=True))
                    click.echo("  /save <text>    Guarda text a memòria")
                    click.echo("  /recall <query> Cerca a memòria")
                    click.echo("  /context on|off Activa/desactiva RAG")
                    click.echo("  /help           Mostra aquesta ajuda")
                    click.echo("  clear           Neteja historial")
                    click.echo("  sortir          Surt del chat\n")
                    continue

                else:
                    click.echo(click.style(f"❓ Comanda desconeguda: /{cmd}", fg="yellow"))
                    click.echo("Escriu /help per veure les comandes disponibles.")
                    continue

            history.append({"role": "user", "content": user_input})

            click.echo(click.style("Nexe: ", fg="cyan", bold=True), nl=False)
            
            full_response = ""
            async for chunk in client.chat_stream(messages=history, engine=engine, rag=rag):
                print(chunk, end="", flush=True)
                full_response += chunk
            
            print() # Newline final
            history.append({"role": "assistant", "content": full_response})

        except KeyboardInterrupt:
            click.echo("\n👋 Adéu!")
            break
        except Exception as e:
            click.echo(f"\n❌ Error client: {e}")
            break

if __name__ == "__main__":
    chat()
