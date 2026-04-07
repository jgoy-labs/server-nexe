"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: core/cli/chat_cli.py
Description: Unified Chat CLI. Detects available engine (MLX, Llama.cpp, Ollama)
             and provides a simple interactive interface.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import os
import re
import time
import itertools
import logging
import asyncio
import click
from pathlib import Path
from typing import Optional, AsyncGenerator

logger = logging.getLogger(__name__)

# Helpers for engine detection
def get_default_system_prompt():
    """Read the system prompt from personality/server.toml if it exists."""
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
    return "You are Nexe, a local AI assistant, precise and secure."

def detect_engine():
    """
    Detect which engine is configured/available.

    Priority:
    1. NEXE_MODEL_ENGINE (set by the installer in .env)
    2. server.toml preferred_engine
    3. Detection via model-specific environment variables
    4. Fallback to ollama
    """
    import os
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib

    # IMPORTANT: Load .env BEFORE reading environment variables
    from dotenv import load_dotenv
    project_root = Path(__file__).parent.parent.parent
    env_path = project_root / ".env"
    if env_path.exists():
        load_dotenv(env_path)

    # 1. HIGHEST PRIORITY: Installer environment variable
    env_engine = os.getenv("NEXE_MODEL_ENGINE")
    if env_engine and env_engine.lower() not in ("auto", ""):
        return env_engine.lower()

    # 2. Try reading from server.toml
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

    # 3. Fallback to env vars for specific models
    if os.getenv("NEXE_MLX_MODEL"):
        return "mlx"
    if os.getenv("NEXE_LLAMA_CPP_MODEL"):
        return "llama_cpp"

    # 4. Final fallback (default)
    return "ollama"


def _format_rag_bar(score: float, width: int = 8) -> str:
    """Generate a proportional Unicode bar for score (0.0-1.0)."""
    filled = int(score * width)
    return "█" * filled + "░" * (width - filled)


def _format_stats_line(elapsed: float, char_count: int, model_name: str = None,
                       rag_count: int = 0, rag_avg: float = 0.0, mem_saved: bool = False,
                       compact_count: int = 0) -> str:
    """Build the stats line displayed after each response."""
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
    """Show an animated spinner until the first text chunk arrives, then stream normally.
    Passes metadata dicts through transparently (no spinner)."""
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
    """Get a streaming response from the configured engine."""
    # Note: This is where real dispatch to modules would happen.
    # For CLI simplicity, we call the local API if the server is up,
    # or instantiate the node directly for "offline chat".

    # At this stage, we delegate to the corresponding module if loaded.
    pass

@click.command()
@click.option('--engine', '-e', type=click.Choice(['mlx', 'llama_cpp', 'ollama']), help='Inference engine')
@click.option('--system', '-s', default=None, help='System prompt / Identity')
@click.option('--no-rag', is_flag=True, help='Disable memory context (RAG)')
@click.option('--model', '-m', help='Model name (for Ollama)')
@click.option('--verbose', '-v', is_flag=True, help='Show RAG detail per source')
@click.option('--rag-threshold', type=float, default=None, help='RAG score threshold (0.20-0.70)')
@click.option('--collections', '-c', default=None, help='Comma-separated collections: memory,knowledge,docs (default: all)')
def chat(engine: Optional[str], system: Optional[str], no_rag: bool, model: Optional[str], verbose: bool,
         rag_threshold: Optional[float], collections: Optional[str]):
    """
    Start an interactive chat with Nexe.
    Auto-detects the configured engine if none is specified.
    """
    asyncio.run(_chat_async(engine, system, no_rag, model, verbose, rag_threshold, collections))

def detect_model():
    """Detect which model is currently configured."""
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


async def _chat_async(engine: Optional[str], system: Optional[str], no_rag: bool, model: Optional[str], verbose: bool = False,
                      rag_threshold: Optional[float] = None, collections: Optional[str] = None):
    from .utils.api_client import NexeAPIClient

    if not engine:
        engine = detect_engine()

    if not model:
        model = detect_model()

    if no_rag:
        click.echo(click.style("ℹ️  --no-rag ignored: the UI pipeline always manages memory context.", fg="yellow"))
    if system:
        click.echo(click.style("ℹ️  --system ignored: the system prompt is managed by the server.", fg="yellow"))

    client = NexeAPIClient()

    # Check server status
    import os as _os
    from core.config import get_server_url
    _nexe_url = _os.environ.get("NEXE_API_BASE_URL", get_server_url()).rstrip("/")
    if not await client.is_server_running():
        click.echo(click.style(f"\n❌ Error: Nexe server not responding at {_nexe_url}", fg="red", bold=True))
        click.echo("Make sure you have run './nexe go' in another terminal before starting the chat.\n")
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
        click.echo(click.style("⚠️  Could not create UI session. Check that the web_ui module is active.", fg="yellow"))
        return

    # Parse collection names to internal IDs
    _COLL_ALIASES = {'memory': 'nexe_web_ui', 'knowledge': 'user_knowledge', 'docs': 'nexe_documentation'}
    _rag_collections = None
    if collections:
        _rag_collections = [_COLL_ALIASES.get(c.strip(), c.strip()) for c in collections.split(',')]
        click.echo(click.style(f"  Collections: {', '.join(_rag_collections)}", fg="cyan"))
    if rag_threshold is not None:
        click.echo(click.style(f"  RAG threshold: {rag_threshold}", fg="cyan"))

    _stream_kwargs = {}
    if rag_threshold is not None:
        _stream_kwargs['rag_threshold'] = rag_threshold
    if _rag_collections is not None:
        _stream_kwargs['rag_collections'] = _rag_collections

    click.echo(f"\n  {click.style('🚀 Nexe Chat', fg='cyan', bold=True)}")
    click.echo(f"  {click.style('Engine:', fg='yellow')} {engine}  |  {click.style('Model:', fg='yellow')} {model}  |  {click.style('Memory:', fg='yellow')} ✅ Active")
    click.echo(click.style('  ─────────────────────────────────────────', dim=True))
    click.echo(click.style('  Commands: /upload <ruta> · /save <text> · /recall <query> · /help', dim=True))
    click.echo(click.style('  Type "exit" or Ctrl+C to quit', dim=True) + "\n")

    while True:
        try:
            user_input = click.prompt(click.style("Tu", fg="green", bold=True))

            if user_input.lower() in ["exit", "quit", "q"]:
                break

            if user_input.lower() == "clear":
                session_id = await client.create_ui_session()
                if session_id:
                    click.echo("🧹 History cleared.")
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
                    # Separate path (spaces escaped with \) from optional message
                    # Ex: /upload /path/Comments\ AI.md what does this doc say?
                    path_parts = re.split(r'(?<!\\) ', cmd_arg.strip(), maxsplit=1)
                    raw_path = path_parts[0].replace("\\ ", " ")
                    follow_up = path_parts[1].strip() if len(path_parts) > 1 else ""
                    file_path = os.path.expanduser(raw_path)
                    if not os.path.isfile(file_path):
                        click.echo(click.style(f"❌ File not found: {file_path}", fg="red"))
                        continue
                    filename = Path(file_path).name
                    click.echo(click.style(f"📎 Uploading {filename}...", fg="yellow"))
                    upload_ok = False
                    try:
                        upload_result = await client.upload_file(file_path, session_id)
                        if not upload_result:
                            click.echo(click.style("❌ Error uploading file. Check that the format is compatible.", fg="red"))
                        else:
                            chunks = upload_result.get("chunks", "?")
                            click.echo(click.style(f"✅ {filename} indexed ({chunks} chunks).", fg="green"))
                            upload_ok = True
                    except Exception as e:
                        click.echo(click.style(f"❌ Error: {e}", fg="red"))
                    # If there is a follow-up message, send it now
                    if upload_ok and follow_up:
                        first = True
                        async for chunk in _stream_with_spinner(client.chat_ui_stream(message=follow_up, session_id=session_id, **_stream_kwargs)):
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
                            ack_prompt = f"The user just asked you to remember this: \"{cmd_arg}\". Reply briefly confirming you will remember it, without repeating all the information."
                            first = True
                            async for chunk in _stream_with_spinner(client.chat_ui_stream(message=ack_prompt, session_id=session_id, **_stream_kwargs)):
                                if first:
                                    first = False
                                    click.echo(click.style("Nexe: ", fg="cyan", bold=True), nl=False)
                                print(chunk, end="", flush=True)
                            print()
                        else:
                            click.echo(click.style("❌ Error saving.", fg="red"))
                    except Exception as e:
                        click.echo(click.style(f"❌ Error: {e}", fg="red"))
                    continue

                elif cmd == "recall" and cmd_arg:
                    try:
                        results = await client.memory_search(cmd_arg)
                        if results:
                            click.echo(click.style("📚 Found in memory:", fg="cyan"))
                            for r in results[:3]:
                                click.echo(f"  • {r.get('content', r)[:100]}...")
                        else:
                            click.echo(click.style("🔍 Nothing found.", dim=True))
                    except Exception as e:
                        click.echo(click.style(f"❌ Error: {e}", fg="red"))
                    continue

                elif cmd == "help":
                    click.echo(click.style("\n📖 Available commands:", fg="cyan", bold=True))
                    click.echo("  /upload <path>  Upload file (PDF, MD, TXT...) for analysis")
                    click.echo("  /save <text>    Save text to memory")
                    click.echo("  /recall <query> Search memory")
                    click.echo("  /help           Show this help")
                    click.echo("  clear           Clear history")
                    click.echo("  exit            Quit the chat\n")
                    continue

                else:
                    click.echo(click.style(f"❓ Unknown command: /{cmd}", fg="yellow"))
                    click.echo("Type /help to see available commands.")
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

            async for chunk in _stream_with_spinner(client.chat_ui_stream(message=user_input, session_id=session_id, **_stream_kwargs)):
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
            click.echo("\n👋 Goodbye!")
            break
        except Exception as e:
            click.echo(f"\n❌ Error client: {e}")
            break

if __name__ == "__main__":
    chat()
