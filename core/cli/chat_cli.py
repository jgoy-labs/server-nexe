"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: core/cli/chat_cli.py
Description: CLI de Chat unificat. Detecta motor disponible (MLX, Llama.cpp, Ollama)
             i proporciona una interfície interactiva simple.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import sys
import os
import re
import time
import itertools
import logging
import asyncio
import click
from pathlib import Path
from typing import Optional, Dict, AsyncGenerator

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


def _format_rag_bar(score: float, width: int = 8) -> str:
    """Genera barra Unicode proporcional al score (0.0-1.0)."""
    filled = int(score * width)
    return "█" * filled + "░" * (width - filled)


def _format_stats_line(elapsed: float, char_count: int, model_name: str = None,
                       rag_count: int = 0, rag_avg: float = 0.0, mem_saved: bool = False,
                       compact_count: int = 0) -> str:
    """Genera línia d'stats post-resposta."""
    tokens_est = char_count // 4
    tok_per_sec = tokens_est / elapsed if elapsed > 0.5 else 0
    parts = [f"{elapsed:.1f}s"]
    if tokens_est > 0:
        parts.append(f"~{tokens_est}tok")
    if tok_per_sec > 0:
        parts.append(f"{tok_per_sec:.0f}t/s")
    if model_name:
        # Shorten model name for display
        short = model_name.split("/")[-1] if "/" in model_name else model_name
        if len(short) > 25:
            short = short[:22] + "..."
        parts.append(short)
    if rag_count > 0:
        bar = _format_rag_bar(rag_avg) if rag_avg > 0 else ""
        pct = f" {rag_avg:.0%}" if rag_avg > 0 else ""
        parts.append(f"RAG:{rag_count} {bar}{pct}")
    if compact_count > 0:
        parts.append(f"COMPACT:{compact_count}")
    if mem_saved:
        parts.append("MEM")
    return " | ".join(parts)


async def _stream_with_spinner(gen: AsyncGenerator) -> AsyncGenerator:
    """Mostra spinner animat fins al primer chunk de text; llavors streaming normal.
    Passa metadata dicts transparentment (sense spinner)."""
    frames = itertools.cycle(["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"])
    stop = asyncio.Event()
    t0 = time.monotonic()

    async def _spin():
        for f in frames:
            if stop.is_set():
                break
            elapsed = time.monotonic() - t0
            print(f"\r  {f} {elapsed:.1f}s", end="", flush=True)
            try:
                await asyncio.wait_for(asyncio.shield(stop.wait()), timeout=0.1)
            except asyncio.TimeoutError:
                pass

    task = asyncio.create_task(_spin())
    try:
        async for chunk in gen:
            # Pass metadata dicts through without affecting spinner
            if isinstance(chunk, dict):
                yield chunk
                continue
            if not stop.is_set():
                stop.set()
                await task
                print(f"\r{' ' * 20}\r", end="", flush=True)
            yield chunk
    finally:
        if not stop.is_set():
            stop.set()
            try:
                await task
            except Exception:
                pass
        print(f"\r{' ' * 20}\r", end="", flush=True)


async def get_response_stream(engine: str, prompt: str, system: str, history: list, use_rag: bool):
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
@click.option('--verbose', '-v', is_flag=True, help='Mostra detall RAG per font')
def chat(engine: Optional[str], system: Optional[str], no_rag: bool, model: Optional[str], verbose: bool):
    """
    Inicia un xat interactiu amb Nexe.
    Detecta automàticament el motor configurat si no s'especifica.
    """
    asyncio.run(_chat_async(engine, system, no_rag, model, verbose))

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


async def _chat_async(engine: Optional[str], system: Optional[str], no_rag: bool, model: Optional[str], verbose: bool = False):
    from .utils.api_client import NexeAPIClient

    if not engine:
        engine = detect_engine()

    if not model:
        model = detect_model()

    if no_rag:
        click.echo(click.style("ℹ️  --no-rag ignorat: el pipeline UI gestiona sempre el context de memòria.", fg="yellow"))
    if system:
        click.echo(click.style("ℹ️  --system ignorat: el system prompt el gestiona el servidor.", fg="yellow"))

    client = NexeAPIClient()

    # Check server status
    import os as _os
    _nexe_url = _os.environ.get("NEXE_API_BASE_URL", "http://127.0.0.1:9119").rstrip("/")
    if not await client.is_server_running():
        click.echo(click.style(f"\n❌ Error: El servidor Nexe no respon a {_nexe_url}", fg="red", bold=True))
        click.echo("Assegura't que has executat './nexe go' en una altra terminal abans d'iniciar el xat.\n")
        return

    # Get actual engine from server status (not just from .env)
    try:
        import httpx
        async with httpx.AsyncClient() as http_client:
            response = await http_client.get(f"{_nexe_url}/status", timeout=5.0)
            if response.status_code == 200:
                status = response.json()
                actual_engine = status.get("engine", engine)
                if actual_engine != engine:
                    engine = f"{actual_engine} (fallback)"
    except Exception:
        pass

    # Create UI session (same pipeline as web UI)
    session_id = await client.create_ui_session()
    if not session_id:
        click.echo(click.style("⚠️  No s'ha pogut crear sessió UI. Comprova que el mòdul web_ui estigui actiu.", fg="yellow"))
        return

    click.echo(f"\n  {click.style('🚀 Nexe Chat', fg='cyan', bold=True)}")
    click.echo(f"  {click.style('Engine:', fg='yellow')} {engine}  |  {click.style('Model:', fg='yellow')} {model}  |  {click.style('Memòria:', fg='yellow')} ✅ Activa")
    click.echo(click.style('  ─────────────────────────────────────────', dim=True))
    click.echo(click.style('  Commands: /upload <ruta> · /save <text> · /recall <query> · /help', dim=True))
    click.echo(click.style('  Type "exit" or Ctrl+C to quit', dim=True) + "\n")

    while True:
        try:
            user_input = click.prompt(click.style("Tu", fg="green", bold=True))

            if user_input.lower() in ["sortir", "exit", "quit", "q"]:
                break

            if user_input.lower() == "clear":
                session_id = await client.create_ui_session()
                if session_id:
                    click.echo("🧹 Historial netejat.")
                else:
                    click.echo(click.style("❌ Error reiniciant sessió.", fg="red"))
                continue

            # Slash commands (only if first token is a known command, not a file path)
            KNOWN_COMMANDS = {"save", "recall", "help", "upload"}
            _first_token = user_input[1:].split()[0].lower() if len(user_input) > 1 else ""
            if user_input.startswith("/") and _first_token in KNOWN_COMMANDS:
                cmd_parts = user_input[1:].split(" ", 1)
                cmd = cmd_parts[0].lower()
                cmd_arg = cmd_parts[1] if len(cmd_parts) > 1 else ""

                if cmd == "upload" and cmd_arg:
                    # Separar ruta (espais escapats amb \) del missatge opcional
                    # Ex: /upload /path/Coments\ IA.md que diu aquest doc?
                    path_parts = re.split(r'(?<!\\) ', cmd_arg.strip(), maxsplit=1)
                    raw_path = path_parts[0].replace("\\ ", " ")
                    follow_up = path_parts[1].strip() if len(path_parts) > 1 else ""
                    file_path = os.path.expanduser(raw_path)
                    if not os.path.isfile(file_path):
                        click.echo(click.style(f"❌ Fitxer no trobat: {file_path}", fg="red"))
                        continue
                    filename = Path(file_path).name
                    click.echo(click.style(f"📎 Pujant {filename}...", fg="yellow"))
                    upload_ok = False
                    try:
                        upload_result = await client.upload_file(file_path, session_id)
                        if not upload_result:
                            click.echo(click.style("❌ Error pujant el fitxer. Comprova que el format és compatible.", fg="red"))
                        else:
                            chunks = upload_result.get("chunks", "?")
                            click.echo(click.style(f"✅ {filename} indexat ({chunks} parts).", fg="green"))
                            upload_ok = True
                    except Exception as e:
                        click.echo(click.style(f"❌ Error: {e}", fg="red"))
                    # Si hi ha missatge de seguiment, enviar-lo ara
                    if upload_ok and follow_up:
                        first = True
                        async for chunk in _stream_with_spinner(client.chat_ui_stream(message=follow_up, session_id=session_id)):
                            if first:
                                first = False
                                click.echo(click.style("Nexe: ", fg="cyan", bold=True), nl=False)
                            print(chunk, end="", flush=True)
                        print()
                    continue

                elif cmd == "save" and cmd_arg:
                    try:
                        success = await client.memory_store(cmd_arg)
                        if success:
                            ack_prompt = f"L'usuari acaba de dir-te que recordis això: \"{cmd_arg}\". Respon breument confirmant que ho recordaràs, sense repetir tota la informació."
                            first = True
                            async for chunk in _stream_with_spinner(client.chat_ui_stream(message=ack_prompt, session_id=session_id)):
                                if first:
                                    first = False
                                    click.echo(click.style("Nexe: ", fg="cyan", bold=True), nl=False)
                                print(chunk, end="", flush=True)
                            print()
                        else:
                            click.echo(click.style("❌ Error guardant.", fg="red"))
                    except Exception as e:
                        click.echo(click.style(f"❌ Error: {e}", fg="red"))
                    continue

                elif cmd == "recall" and cmd_arg:
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

                elif cmd == "help":
                    click.echo(click.style("\n📖 Comandes disponibles:", fg="cyan", bold=True))
                    click.echo("  /upload <ruta>  Puja fitxer (PDF, MD, TXT...) per analitzar")
                    click.echo("  /save <text>    Guarda text a memòria")
                    click.echo("  /recall <query> Cerca a memòria")
                    click.echo("  /help           Mostra aquesta ajuda")
                    click.echo("  clear           Neteja historial")
                    click.echo("  sortir          Surt del chat\n")
                    continue

                else:
                    click.echo(click.style(f"❓ Comanda desconeguda: /{cmd}", fg="yellow"))
                    click.echo("Escriu /help per veure les comandes disponibles.")
                    continue

            first = True
            t_start = time.monotonic()
            char_count = 0
            _model_name = None
            _rag_count = 0
            _rag_avg = 0.0
            _rag_items = []
            _mem_saved = False
            _compact_count = 0

            async for chunk in _stream_with_spinner(client.chat_ui_stream(message=user_input, session_id=session_id)):
                if isinstance(chunk, dict):
                    # Metadata from server
                    if "MODEL" in chunk:
                        _model_name = chunk["MODEL"]
                    if "RAG" in chunk:
                        try: _rag_count = int(chunk["RAG"])
                        except (ValueError, TypeError): pass
                    if "RAG_AVG" in chunk:
                        try: _rag_avg = float(chunk["RAG_AVG"])
                        except (ValueError, TypeError): pass
                    if "RAG_ITEM" in chunk:
                        # Format: "collection|score"
                        parts = chunk["RAG_ITEM"].split("|", 1)
                        if len(parts) == 2:
                            try: _rag_items.append((parts[0], float(parts[1])))
                            except (ValueError, TypeError): pass
                    if "MEM" in chunk:
                        _mem_saved = True
                    if "COMPACT" in chunk:
                        try: _compact_count = int(chunk["COMPACT"])
                        except (ValueError, TypeError): pass
                    continue

                if first:
                    first = False
                    click.echo(click.style("Nexe: ", fg="cyan", bold=True), nl=False)
                char_count += len(chunk)
                print(chunk, end="", flush=True)

            elapsed = time.monotonic() - t_start
            stats = _format_stats_line(elapsed, char_count, _model_name, _rag_count, _rag_avg, _mem_saved, _compact_count)
            print(click.style(f"  [{stats}]", dim=True))

            # Verbose RAG detail
            if verbose and _rag_items:
                for col, score in _rag_items:
                    bar = _format_rag_bar(score, 10)
                    color = "green" if score >= 0.8 else "yellow" if score >= 0.6 else "red"
                    click.echo(click.style(f"    {col:<15} {bar} {score:.0%}", fg=color))

        except KeyboardInterrupt:
            click.echo("\n👋 Adéu!")
            break
        except Exception as e:
            click.echo(f"\n❌ Error client: {e}")
            break

if __name__ == "__main__":
    chat()
