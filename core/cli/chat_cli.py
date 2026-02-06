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

from .i18n import t

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
    return t("cli.chat.default_system_prompt", "You are Nexe, a precise and secure local AI assistant.")

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
@click.option('--engine', '-e', type=click.Choice(['mlx', 'llama_cpp', 'ollama']),
              help=t("cli.chat.options.engine", "Inference engine"))
@click.option('--system', '-s', default=None,
              help=t("cli.chat.options.system", "System prompt / Identity"))
@click.option('--no-rag', is_flag=True,
              help=t("cli.chat.options.no_rag", "Disable memory context (RAG)"))
@click.option('--model', '-m',
              help=t("cli.chat.options.model", "Model name (for Ollama)"))
def chat(engine: Optional[str], system: Optional[str], no_rag: bool, model: Optional[str]):
    """
    Start an interactive chat with Nexe.
    Detects the configured engine automatically if not specified.
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
        click.echo(click.style(
            "\n" + t(
                "cli.chat.server_not_responding",
                "❌ Error: Nexe server is not responding at http://127.0.0.1:9119"
            ),
            fg="red",
            bold=True
        ))
        click.echo(t(
            "cli.chat.server_not_responding_hint",
            "Make sure you've run './nexe go' in another terminal before starting chat.\n"
        ))
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

    click.echo(f"\n  {click.style(t('cli.chat.header_title', '🚀 Nexe Chat'), fg='cyan', bold=True)}")
    rag_label = t("cli.chat.rag_on", "✅ On") if rag else t("cli.chat.rag_off", "❌ Off")
    click.echo(
        f"  {click.style(t('cli.chat.label.engine', 'Engine:'), fg='yellow')} {engine}  |  "
        f"{click.style(t('cli.chat.label.model', 'Model:'), fg='yellow')} {model}  |  "
        f"{click.style(t('cli.chat.label.rag', 'RAG:'), fg='yellow')} {rag_label}"
    )
    click.echo(click.style('  ─────────────────────────────────────────', dim=True))
    click.echo(click.style(
        f"  {t('cli.chat.commands_line', 'Commands: /save <text> · /recall <query> · /context on|off · /help')}",
        dim=True
    ))
    click.echo(click.style(
        "  " + t('cli.chat.quit_line', 'Type "exit" or Ctrl+C to quit'),
        dim=True
    ) + "\n")

    history = []
    if system:
        history.append({"role": "system", "content": system})
    
    while True:
        try:
            user_input = click.prompt(click.style(t("cli.chat.prompt_user", "You"), fg="green", bold=True))

            if user_input.lower() in ["sortir", "exit", "quit", "q"]:
                break

            if user_input.lower() == "clear":
                history = [h for h in history if h["role"] == "system"]
                click.echo(t("cli.chat.history_cleared", "🧹 History cleared."))
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
                            ack_prompt = t(
                                "cli.chat.save_ack_prompt",
                                "The user asked you to remember this: \"{text}\". Respond briefly confirming you will remember it, without repeating all information.",
                                text=cmd_arg
                            )
                            history.append({"role": "user", "content": ack_prompt})

                            click.echo(click.style(t("cli.chat.prompt_assistant", "Nexe: "), fg="cyan", bold=True), nl=False)
                            full_response = ""
                            async for chunk in client.chat_stream(messages=history, engine=engine, rag=False):
                                print(chunk, end="", flush=True)
                                full_response += chunk
                            print()

                            # Replace the ack_prompt with original save content in history
                            history[-1] = {"role": "user", "content": t(
                                "cli.chat.save_memory_marker",
                                "[Saved to memory: {text}]",
                                text=cmd_arg
                            )}
                            history.append({"role": "assistant", "content": full_response})
                        else:
                            click.echo(click.style(t("cli.chat.save_error", "❌ Error saving."), fg="red"))
                    except Exception as e:
                        click.echo(click.style(
                            t("cli.chat.error_generic", "❌ Error: {error}", error=str(e)),
                            fg="red"
                        ))
                    continue

                elif cmd == "recall" and cmd_arg:
                    # Search memory
                    try:
                        results = await client.memory_search(cmd_arg)
                        if results:
                            click.echo(click.style(t("cli.chat.memory_found", "📚 Found in memory:"), fg="cyan"))
                            for r in results[:3]:
                                click.echo(f"  • {r.get('content', r)[:100]}...")
                        else:
                            click.echo(click.style(t("cli.chat.memory_not_found", "🔍 Nothing found."), dim=True))
                    except Exception as e:
                        click.echo(click.style(
                            t("cli.chat.error_generic", "❌ Error: {error}", error=str(e)),
                            fg="red"
                        ))
                    continue

                elif cmd == "context":
                    if cmd_arg.lower() == "off":
                        rag = False
                        click.echo(click.style(t("cli.chat.rag_disabled", "🔕 RAG context disabled."), fg="yellow"))
                    elif cmd_arg.lower() == "on":
                        rag = True
                        click.echo(click.style(t("cli.chat.rag_enabled", "🔔 RAG context enabled."), fg="green"))
                    else:
                        status = t("cli.chat.rag_status_on", "✅ Active") if rag else t("cli.chat.rag_status_off", "❌ Inactive")
                        click.echo(t("cli.chat.rag_status", "RAG: {status}", status=status))
                    continue

                elif cmd == "help":
                    click.echo(click.style("\n" + t("cli.chat.help_title", "📖 Available commands:"), fg="cyan", bold=True))
                    click.echo(t("cli.chat.help.save", "  /save <text>    Save text to memory"))
                    click.echo(t("cli.chat.help.recall", "  /recall <query> Search memory"))
                    click.echo(t("cli.chat.help.context", "  /context on|off Enable/disable RAG"))
                    click.echo(t("cli.chat.help.help", "  /help           Show this help"))
                    click.echo(t("cli.chat.help.clear", "  clear           Clear history"))
                    click.echo(t("cli.chat.help.exit", "  exit            Exit chat\n"))
                    continue

                else:
                    click.echo(click.style(
                        t("cli.chat.unknown_command", "❓ Unknown command: /{cmd}", cmd=cmd),
                        fg="yellow"
                    ))
                    click.echo(t("cli.chat.help_hint", "Type /help to see available commands."))
                    continue

            history.append({"role": "user", "content": user_input})

            click.echo(click.style(t("cli.chat.prompt_assistant", "Nexe: "), fg="cyan", bold=True), nl=False)
            
            full_response = ""
            async for chunk in client.chat_stream(messages=history, engine=engine, rag=rag):
                print(chunk, end="", flush=True)
                full_response += chunk
            
            print() # Newline final
            history.append({"role": "assistant", "content": full_response})

        except KeyboardInterrupt:
            click.echo(t("cli.chat.goodbye", "\n👋 Goodbye!"))
            break
        except Exception as e:
            click.echo(t("cli.chat.client_error", "\n❌ Client error: {error}", error=str(e)))
            break

if __name__ == "__main__":
    chat()
