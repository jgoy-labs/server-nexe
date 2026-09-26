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
# pyright: reportCallIssue=false
# Click @command decorator transforms `chat(...)` into a Command at runtime;
# the bare `chat()` invocation in __main__ is handled by click's arg parsing.

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
def detect_engine() -> str:
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
        import tomli as tomllib  # type: ignore[no-redef]

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
                if engine and engine != "auto":
                    return str(engine)
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
@click.option('--attach', '-a', type=click.Path(), default=None, help='Attach a file to the session before the first message (same upload /upload does interactively)')
@click.option('--show-thinking', is_flag=True, help="Show the model's reasoning in full (folded into one line by default)")
def chat(engine: Optional[str], system: Optional[str], no_rag: bool, model: Optional[str], verbose: bool,
         rag_threshold: Optional[float], collections: Optional[str], attach: Optional[str],
         show_thinking: bool = False):
    """
    Start an interactive chat with Nexe.
    Auto-detects the configured engine if none is specified.
    """
    asyncio.run(_chat_async(engine, system, no_rag, model, verbose, rag_threshold, collections, attach,
                            show_thinking=show_thinking))

def detect_model() -> str:
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
    from core.memory_access import DOCS_COLLECTION, MEMORY_COLLECTION
    _COLL_ALIASES = {'memory': MEMORY_COLLECTION, 'knowledge': DOCS_COLLECTION, 'docs': DOCS_COLLECTION}
    if not collections_str:
        return None
    return [_COLL_ALIASES.get(c.strip(), c.strip()) for c in collections_str.split(',')]


async def _upload_attachment(file_path: str, client: Any, session_id: str) -> bool:
    """Upload one file to the session, echoing the same messages `/upload`
    has always shown. Shared by `/upload` (interactive) and `--attach`
    (#1081, at startup) — the flag is repointed at `upload_file`, not a
    second upload path."""
    if not os.path.isfile(file_path):
        click.echo(click.style(f"❌ File not found: {file_path}", fg="red"))
        return False
    filename = Path(file_path).name
    click.echo(click.style(f"📎 Uploading {filename}...", fg="yellow"))
    try:
        upload_result = await client.upload_file(file_path, session_id)
    except Exception as e:
        click.echo(click.style(f"❌ Error: {e}", fg="red"))
        return False
    if not upload_result:
        click.echo(click.style("❌ Error uploading file. Check that the format is compatible.", fg="red"))
        return False
    chunks = upload_result.get("chunks", "?")
    click.echo(click.style(f"✅ {filename} indexed ({chunks} chunks).", fg="green"))
    return True


async def _cmd_upload(cmd_arg: str, client: Any, session_id: str, stream_kwargs: dict) -> None:
    path_parts = re.split(r'(?<!\\) ', cmd_arg.strip(), maxsplit=1)
    raw_path = path_parts[0].replace("\\ ", " ")
    follow_up = path_parts[1].strip() if len(path_parts) > 1 else ""
    file_path = os.path.expanduser(raw_path)
    upload_ok = await _upload_attachment(file_path, client, session_id)
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


def _process_memory_markers(chunk: dict, state: dict) -> None:
    """What the turn forgot, and what it wants to forget (the web badges' source)."""
    if "DEL" in chunk:
        # \x00[DEL:N:fact1|fact2]\x00
        _n, _, facts = str(chunk["DEL"]).partition(":")
        state["deleted"] = [f for f in facts.split("|") if f]
    if "PENDING_DELETE" in chunk:
        state["pending_delete"] = chunk["PENDING_DELETE"]


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
        _note_mem(str(chunk["MEM"]), state)
    _process_memory_markers(chunk, state)
    if "COMPACT" in chunk:
        try:
            state["compact_count"] = int(chunk["COMPACT"])
        except (ValueError, TypeError):
            pass


def _on_reasoning(text: str, state: dict, show_thinking: bool) -> None:
    """The model's reasoning: counted, and printed dim only when asked."""
    if show_thinking:
        if not state["reasoning"]:
            click.echo(click.style("💭 ", dim=True), nl=False)
        click.echo(click.style(text, dim=True), nl=False)
    state["reasoning"] += text


def _open_answer(state: dict, show_thinking: bool) -> None:
    """Before the first word of the answer: fold the reasoning into one line."""
    if state["reasoning"]:
        if show_thinking:
            click.echo()
        else:
            tokens = max(1, len(state["reasoning"]) // 4)
            click.echo(click.style(f"💭 raonament (~{tokens} tok) — --show-thinking per veure'l", dim=True))
    click.echo(click.style("Nexe: ", fg="cyan", bold=True), nl=False)


def _note_mem(value: str, state: dict) -> None:
    """[MEM:n:fact1|fact2] — what memory kept this turn, as the server says
    (#1098). n = stored new; [MEM:n] alone comes from the continue path;
    [MEM:0] means nothing was kept."""
    count, _, listed = value.partition(":")
    kept = [f for f in listed.split("|") if f]
    state["saved_facts"] = list(dict.fromkeys(state.get("saved_facts", []) + kept))
    if kept or not count.isdigit() or int(count) > 0:
        state["mem_saved"] = True


async def _report_memory(state: dict, client: Any, session_id: str) -> None:
    """Saved / forgotten facts, as the web UI's badges; a pending forget is asked.

    `session_id` (C4.5): the confirmation deletes THE entry this session has
    pending, by id — the same call the web dialog makes.
    """
    # Only what the server says memory kept ([MEM:n:facts]): a model can write
    # a [MEM_SAVE:] the server then refuses (seen 25/09: gemma3 tagging "my
    # name is Nexe" on its own), and saying "saved" there would be a lie. The
    # model's own tags never feed this (#1098).
    facts = state["saved_facts"]
    if facts:
        click.echo(click.style("  💾 Desat: " + "; ".join(facts), fg="green"))
    elif state["mem_saved"]:
        click.echo(click.style("  💾 Desat", fg="green"))
    if state["deleted"]:
        click.echo(click.style("  🗑 Esborrat: " + "; ".join(state["deleted"]), fg="yellow"))
    fact = state["pending_delete"]
    if fact and click.confirm(f'  Vols que oblidi "{fact}"?', default=False):
        result = await client.memory_confirm_delete(fact, session_id)
        gone = [f.get("text", f) if isinstance(f, dict) else f for f in result.get("deleted_facts", [])]
        if result.get("deleted"):
            click.echo(click.style("  🗑 Esborrat: " + "; ".join(map(str, gone or [fact])), fg="yellow"))
        else:
            click.echo(click.style("  No he trobat res a esborrar.", dim=True))


async def _handle_user_message(
    user_input: str, client: Any,
    session_id: str, stream_kwargs: dict, verbose: bool,
    show_thinking: bool = False,
) -> None:
    """Streaming complet + stats + verbose RAG."""
    first = True
    t_start = time.monotonic()
    char_count = 0
    state: dict = {
        "model_name": None, "rag_count": 0, "rag_avg": 0.0,
        "rag_items": [], "mem_saved": False, "compact_count": 0,
        "reasoning": "", "saved_facts": [], "deleted": [], "pending_delete": None,
    }

    async for chunk in _stream_with_spinner(client.chat_ui_stream(message=user_input, session_id=session_id, **stream_kwargs)):
        if isinstance(chunk, dict):
            if chunk.get("type") == "reasoning":
                _on_reasoning(chunk["text"], state, show_thinking)
            elif chunk.get("type") == "memory_tags":
                pass  # the model's own tags: a request, never "saved" (#1098)
            else:
                _process_metadata_chunk(chunk, state)
            continue
        if first:
            first = False
            _open_answer(state, show_thinking)
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

    await _report_memory(state, client, session_id)


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
        api_key = os.environ.get("NEXE_PRIMARY_API_KEY") or os.environ.get("NEXE_ADMIN_API_KEY")
        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
            headers["x-api-key"] = api_key
        async with httpx.AsyncClient() as http_client:
            response = await http_client.get(f"{nexe_url}/status", timeout=5.0, headers=headers)
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


async def _chat_handle_input(user_input: str, client, session_id: str, stream_kwargs: dict, verbose: bool,
                             show_thinking: bool = False) -> "tuple[bool, str]":
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

    await _handle_user_message(user_input, client, session_id, stream_kwargs, verbose, show_thinking)
    return False, session_id


async def _chat_async(engine: Optional[str], system: Optional[str], no_rag: bool, model: Optional[str], verbose: bool = False,
                      rag_threshold: Optional[float] = None, collections: Optional[str] = None,
                      attach: Optional[str] = None, show_thinking: bool = False):
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

    if attach and not await _upload_attachment(os.path.expanduser(attach), client, session_id):
        # The user asked for this file explicitly. Dropping into the chat
        # anyway puts the ❌ three lines above a "🚀 Nexe Chat / Memory: ✅
        # Active" banner and lets them talk to a document that was never
        # indexed — continuing without it would be deciding for them.
        raise SystemExit(1)

    click.echo(f"\n  {click.style('🚀 Nexe Chat', fg='cyan', bold=True)}")
    click.echo(f"  {click.style('Engine:', fg='yellow')} {engine}  |  {click.style('Model:', fg='yellow')} {model}  |  {click.style('Memory:', fg='yellow')} ✅ Active")
    click.echo(click.style('  ─────────────────────────────────────────', dim=True))
    click.echo(click.style('  Commands: /upload <ruta> · /save <text> · /recall <query> · /help', dim=True))
    click.echo(click.style('  Type "exit" or Ctrl+C to quit', dim=True) + "\n")

    while True:
        try:
            user_input = click.prompt(click.style("Tu", fg="green", bold=True))
            should_break, session_id = await _chat_handle_input(
                user_input, client, session_id, _stream_kwargs, verbose, show_thinking,
            )
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
