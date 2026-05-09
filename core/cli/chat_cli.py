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
from typing import Any, Optional, AsyncGenerator

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


def _format_stats_line(elapsed: float, char_count: int, model_name: Optional[str] = None,
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
            except Exception:  # nosec B110: best-effort spinner task cancellation; failure here is benign UI cleanup
                pass
        print(f"\r{' ' * 20}\r", end="", flush=True)


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


async def _resolve_chat_engine_and_model(
    engine: Optional[str], model: Optional[str]
) -> tuple[str, str]:
    if not engine:
        engine = detect_engine()
    if not model:
        model = detect_model()
    return engine, model


async def _check_server_status(client: Any) -> bool:
    return await client.is_server_running()


async def _create_chat_session(client: Any) -> Optional[str]:
    return await client.create_ui_session()


def _parse_collections(collections_str: Optional[str]) -> Optional[list[str]]:
    _COLL_ALIASES = {'memory': 'personal_memory', 'knowledge': 'nexe_documentation', 'docs': 'nexe_documentation'}
    if not collections_str:
        return None
    return [_COLL_ALIASES.get(c.strip(), c.strip()) for c in collections_str.split(',')]


async def _cmd_upload(cmd_arg: str, client: Any, session_id: str, stream_kwargs: dict) -> None:
    path_parts = re.split(r'(?<!\\) ', cmd_arg.strip(), maxsplit=1)
    raw_path = path_parts[0].replace("\\ ", " ")
    follow_up = path_parts[1].strip() if len(path_parts) > 1 else ""
    file_path = os.path.expanduser(raw_path)
    if not os.path.isfile(file_path):
        click.echo(click.style(f"❌ File not found: {file_path}", fg="red"))
        return
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
    if upload_ok and follow_up:
        first = True
        async for chunk in _stream_with_spinner(client.chat_ui_stream(message=follow_up, session_id=session_id, **stream_kwargs)):
            if first:
                first = False
                click.echo(click.style("Nexe: ", fg="cyan", bold=True), nl=False)
            print(chunk, end="", flush=True)
        print()


async def _cmd_save(cmd_arg: str, client: Any, session_id: str, stream_kwargs: dict) -> None:
    try:
        success = await client.memory_store(cmd_arg)
        if success:
            ack_prompt = f"The user just asked you to remember this: \"{cmd_arg}\". Reply briefly confirming you will remember it, without repeating all the information."
            first = True
            async for chunk in _stream_with_spinner(client.chat_ui_stream(message=ack_prompt, session_id=session_id, **stream_kwargs)):
                if first:
                    first = False
                    click.echo(click.style("Nexe: ", fg="cyan", bold=True), nl=False)
                print(chunk, end="", flush=True)
            print()
        else:
            click.echo(click.style("❌ Error saving.", fg="red"))
    except Exception as e:
        click.echo(click.style(f"❌ Error: {e}", fg="red"))


async def _cmd_recall(cmd_arg: str, client: Any) -> None:
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


async def _handle_slash_command(
    cmd: str, cmd_arg: str, client: Any,
    session_id: str, stream_kwargs: dict
) -> bool:
    """Returns True if processed (caller must continue the loop)."""
    _session_cmds = {"upload": _cmd_upload, "save": _cmd_save}
    if cmd in _session_cmds and cmd_arg:
        await _session_cmds[cmd](cmd_arg, client, session_id, stream_kwargs)
    elif cmd == "recall" and cmd_arg:
        await _cmd_recall(cmd_arg, client)
    elif cmd == "help":
        click.echo(click.style("\n📖 Available commands:", fg="cyan", bold=True))
        click.echo("  /upload <path>  Upload file (PDF, MD, TXT...) for analysis")
        click.echo("  /save <text>    Save text to memory")
        click.echo("  /recall <query> Search memory")
        click.echo("  /help           Show this help")
        click.echo("  clear           Clear history")
        click.echo("  exit            Quit the chat\n")
    else:
        click.echo(click.style(f"❓ Unknown command: /{cmd}", fg="yellow"))
        click.echo("Type /help to see available commands.")
    return True


def _process_metadata_chunk(chunk: dict, state: dict) -> None:
    """Updates the mutable state with MODEL, RAG, RAG_AVG, etc."""
    if "MODEL" in chunk:
        state["model_name"] = chunk["MODEL"]
    if "RAG" in chunk:
        try:
            state["rag_count"] = int(chunk["RAG"])
        except (ValueError, TypeError):
            pass
    if "RAG_AVG" in chunk:
        try:
            state["rag_avg"] = float(chunk["RAG_AVG"])
        except (ValueError, TypeError):
            pass
    if "RAG_ITEM" in chunk:
        parts = chunk["RAG_ITEM"].split("|", 1)
        if len(parts) == 2:
            try:
                state["rag_items"].append((parts[0], float(parts[1])))
            except (ValueError, TypeError):
                pass
    if "MEM" in chunk:
        state["mem_saved"] = True
    if "COMPACT" in chunk:
        try:
            state["compact_count"] = int(chunk["COMPACT"])
        except (ValueError, TypeError):
            pass


async def _handle_user_message(
    user_input: str, client: Any,
    session_id: str, stream_kwargs: dict, verbose: bool
) -> None:
    """Streaming complet + stats + verbose RAG."""
    first = True
    t_start = time.monotonic()
    char_count = 0
    state: dict = {
        "model_name": None, "rag_count": 0, "rag_avg": 0.0,
        "rag_items": [], "mem_saved": False, "compact_count": 0,
    }

    async for chunk in _stream_with_spinner(client.chat_ui_stream(message=user_input, session_id=session_id, **stream_kwargs)):
        if isinstance(chunk, dict):
            _process_metadata_chunk(chunk, state)
            continue
        if first:
            first = False
            click.echo(click.style("Nexe: ", fg="cyan", bold=True), nl=False)
        char_count += len(chunk)
        print(chunk, end="", flush=True)

    elapsed = time.monotonic() - t_start
    stats = _format_stats_line(elapsed, char_count, state["model_name"], state["rag_count"], state["rag_avg"], state["mem_saved"], state["compact_count"])
    print(click.style(f"  [{stats}]", dim=True))

    if verbose and state["rag_items"]:
        for col, score in state["rag_items"]:
            bar = _format_rag_bar(score, 10)
            color = "green" if score >= 0.8 else "yellow" if score >= 0.6 else "red"
            click.echo(click.style(f"    {col:<15} {bar} {score:.0%}", fg=color))


def _chat_emit_ignored_flags(no_rag: bool, system: Optional[str]) -> None:
    """Warn about CLI flags that are ignored by the UI pipeline."""
    if no_rag:
        click.echo(click.style("ℹ️  --no-rag ignored: the UI pipeline always manages memory context.", fg="yellow"))
    if system:
        click.echo(click.style("ℹ️  --system ignored: the system prompt is managed by the server.", fg="yellow"))


async def _chat_resolve_actual_engine(nexe_url: str, engine: str) -> str:
    """Best-effort query of /status to detect actual engine (e.g. fallback). Returns updated engine string."""
    try:
        import httpx
        async with httpx.AsyncClient() as http_client:
            response = await http_client.get(f"{nexe_url}/status", timeout=5.0)
            if response.status_code == 200:
                status = response.json()
                actual_engine = status.get("engine", engine)
                if actual_engine != engine:
                    return f"{actual_engine} (fallback)"
    except Exception:  # nosec B110: best-effort engine status fetch; on failure keep the engine value from CLI/.env
        pass
    return engine


def _chat_build_stream_kwargs(collections: Optional[str], rag_threshold: Optional[float]) -> "dict[str, Any]":
    """Build and return the stream_kwargs dict from RAG options, echoing active settings."""
    _rag_collections = _parse_collections(collections)
    _stream_kwargs: dict[str, Any] = {}
    if _rag_collections:
        click.echo(click.style(f"  Collections: {', '.join(_rag_collections)}", fg="cyan"))
        _stream_kwargs['rag_collections'] = _rag_collections
    if rag_threshold is not None:
        click.echo(click.style(f"  RAG threshold: {rag_threshold}", fg="cyan"))
        _stream_kwargs['rag_threshold'] = rag_threshold
    return _stream_kwargs


async def _chat_handle_input(user_input: str, client, session_id: str, stream_kwargs: dict, verbose: bool) -> "tuple[bool, str]":
    """Handle a single line of user input.

    Returns (should_break, updated_session_id).
    """
    if user_input.lower() in ["exit", "quit", "q"]:
        return True, session_id

    if user_input.lower() == "clear":
        new_session_id = await client.create_ui_session()
        if new_session_id:
            session_id = new_session_id
            click.echo("🧹 History cleared.")
        else:
            click.echo(click.style("❌ Error reiniciant sessió.", fg="red"))
        return False, session_id

    KNOWN_COMMANDS = {"save", "recall", "help", "upload"}
    _first_token = user_input[1:].split()[0].lower() if len(user_input) > 1 else ""
    if user_input.startswith("/") and _first_token in KNOWN_COMMANDS:
        cmd_parts = user_input[1:].split(" ", 1)
        cmd = cmd_parts[0].lower()
        cmd_arg = cmd_parts[1] if len(cmd_parts) > 1 else ""
        await _handle_slash_command(cmd, cmd_arg, client, session_id, stream_kwargs)
        return False, session_id

    await _handle_user_message(user_input, client, session_id, stream_kwargs, verbose)
    return False, session_id


async def _chat_async(engine: Optional[str], system: Optional[str], no_rag: bool, model: Optional[str], verbose: bool = False,
                      rag_threshold: Optional[float] = None, collections: Optional[str] = None):
    from .utils.api_client import NexeAPIClient

    engine, model = await _resolve_chat_engine_and_model(engine, model)

    _chat_emit_ignored_flags(no_rag, system)

    client = NexeAPIClient()

    import os as _os
    from core.config import get_server_url
    _nexe_url = _os.environ.get("NEXE_API_BASE_URL", get_server_url()).rstrip("/")
    if not await _check_server_status(client):
        click.echo(click.style(f"\n❌ Error: Nexe server not responding at {_nexe_url}", fg="red", bold=True))
        click.echo("Make sure you have run './nexe go' in another terminal before starting the chat.\n")
        return

    engine = await _chat_resolve_actual_engine(_nexe_url, engine)

    session_id = await _create_chat_session(client)
    if not session_id:
        click.echo(click.style("⚠️  Could not create UI session. Check that the web_ui module is active.", fg="yellow"))
        return

    _stream_kwargs = _chat_build_stream_kwargs(collections, rag_threshold)

    click.echo(f"\n  {click.style('🚀 Nexe Chat', fg='cyan', bold=True)}")
    click.echo(f"  {click.style('Engine:', fg='yellow')} {engine}  |  {click.style('Model:', fg='yellow')} {model}  |  {click.style('Memory:', fg='yellow')} ✅ Active")
    click.echo(click.style('  ─────────────────────────────────────────', dim=True))
    click.echo(click.style('  Commands: /upload <ruta> · /save <text> · /recall <query> · /help', dim=True))
    click.echo(click.style('  Type "exit" or Ctrl+C to quit', dim=True) + "\n")

    while True:
        try:
            user_input = click.prompt(click.style("Tu", fg="green", bold=True))
            should_break, session_id = await _chat_handle_input(user_input, client, session_id, _stream_kwargs, verbose)
            if should_break:
                break
        except KeyboardInterrupt:
            click.echo("\n👋 Goodbye!")
            break
        except Exception as e:
            click.echo(f"\n❌ Error client: {e}")
            break

if __name__ == "__main__":
    chat()
