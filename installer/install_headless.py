"""
────────────────────────────────────
Server Nexe
Location: installer/install_headless.py
Description: Non-interactive installer orchestrator for the GUI wizard.
             Receives config via JSON on stdin, emits [PROGRESS] markers on stdout.
             The GUI parses these markers to update the progress screen.
────────────────────────────────────
"""

import builtins
import json
import logging
import os
import platform
import subprocess  # nosec B404: subprocess required for headless installer venv setup, embeddings download, knowledge ingest; argv built from internal Path/catalog
import sys
import time
import threading
import traceback
import warnings
from datetime import datetime
from pathlib import Path

# Bug 3 (2026-04-06) — silence HuggingFace warnings in the GUI log.
# Previously `Please set a HF_TOKEN...` reached the GUI during headless
# installation and confused users. We now disable telemetry, progress bars
# and specific warnings before any HF import can emit them.
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("HF_HUB_DISABLE_IMPLICIT_TOKEN", "1")
warnings.filterwarnings("ignore", message=".*HF_TOKEN.*")
logging.getLogger("huggingface_hub").setLevel(logging.ERROR)

# Import root: parent of installer/ package (works from both app bundle and repo)
_import_root = str(Path(__file__).parent.parent.resolve())
if _import_root not in sys.path:
    sys.path.insert(0, _import_root)

# Project root — prefer NEXE_PROJECT_ROOT env var (set by launcher)
_env_root = os.environ.get("NEXE_PROJECT_ROOT")
PROJECT_ROOT = Path(_env_root).resolve() if _env_root else Path(__file__).parent.parent.resolve()

from installer.installer_hardware import detect_hardware  # noqa: E402  # after sys.path setup
from installer.installer_catalog_data import MODEL_CATALOG  # noqa: E402  # after sys.path setup
from installer.installer_setup_env import setup_environment  # noqa: E402  # after sys.path setup
from installer.installer_setup_config import generate_env_file  # noqa: E402  # after sys.path setup
from installer.installer_setup_models import (  # noqa: E402  # after sys.path setup
    ensure_ollama_installed,
    _download_ollama_model,
    _download_gguf_model,
    _download_mlx_model,
)
from installer.installer_finalize import _write_commands_file  # noqa: E402  # after sys.path setup
from installer.installer_reinstall import (  # noqa: E402  # after sys.path setup
    DEFAULT_REINSTALL_MODE,
    VALID_REINSTALL_MODES,
    apply_reinstall_mode,
    detect_existing_install,
)

# ═══════════════════════════════════════════════════════════════════════════
# INSTALLATION LOG — persistent file for debugging failures
# ═══════════════════════════════════════════════════════════════════════════
# Dev #3 fix (Consultant pass 1, finding 3): previously LOG_DIR was
# PROJECT_ROOT/storage/logs, but `apply_reinstall_mode(BACKUP)` moves
# `storage/` to `.nexe-backups/` and the FileHandler keeps writing to a
# dead fd. Installation logs now live at ~/.nexe/install_logs/, outside
# the project_root, persisting across installs and immune to the
# installer's backup/wipe.
LOG_DIR = Path.home() / ".nexe" / "install_logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / f"log_installer_error_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

_file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
_file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
_log = logging.getLogger("nexe.installer")
_log.setLevel(logging.DEBUG)
_log.addHandler(_file_handler)

# ═══════════════════════════════════════════════════════════════════════════
# PROGRESS PROTOCOL
# ═══════════════════════════════════════════════════════════════════════════
# The GUI reads stdout line-by-line and looks for these markers:
#   [PROGRESS] step=<N> status=<pending|running|done|error> [msg=<text>]
#   [API_KEY] <key>
#   [DONE]                          — installation completed successfully
#   [DONE_PARTIAL] <reason>         — installation completed but with issues (e.g. model_download_failed)
#   [ERROR] <message>               — fatal error, installation aborted
#
# Steps:
#   1 = Create virtual environment
#   2 = Install dependencies
#   3 = Download model
#   4 = Configure .env
#   5 = Download Qdrant
#   6 = Download embeddings
#   7 = Process knowledge base
# ═══════════════════════════════════════════════════════════════════════════

STEPS = {
    1: "venv",
    2: "deps",
    3: "model",
    4: "config",
    5: "qdrant",
    6: "embeddings",
    7: "knowledge",
}


def _model_id_for_engine(model, engine):
    """Map installer engine keys to model catalog keys."""
    if engine == "llama_cpp":
        return model.get("gguf")
    return model.get(engine)


def _write_project_marker(app_bundle, project_root):
    """Persist the real install path OUTSIDE Nexe.app to preserve codesigning seal.

    Writing inside Contents/Resources/ breaks the bundle's sealed signature
    (Gatekeeper refuses with 'a sealed resource is missing or invalid' and
    'Nexe.app is damaged'). Marker lives at user level, outside any signed
    bundle, readable by the Swift launcher via resolveProjectRoot().

    Note: `app_bundle` kept as argument for backward compat — not used now.
    """
    _ = app_bundle  # keep signature compat
    marker_dir = Path(os.path.expanduser("~/Library/Application Support/Nexe"))
    marker_dir.mkdir(parents=True, exist_ok=True)
    marker = marker_dir / "project_root.txt"
    marker.write_text(str(project_root), encoding="utf-8")


def emit(step, status, msg=""):
    """Emit a progress marker to stdout and log to file."""
    line = f"[PROGRESS] step={step} status={status}"
    if msg:
        # Sanitize: newlines would break the line-based protocol
        line += f" msg={msg.replace(chr(10), ' ').replace(chr(13), '')}"
    print(line, flush=True)
    _log.info(f"step={step} ({STEPS.get(step, '?')}) → {status}" + (f": {msg}" if msg else ""))


def run_headless(config):
    """Run the full installation non-interactively.

    Args:
        config: dict with keys:
            - lang: "ca" | "es" | "en"
            - path: str — project root path
            - model_key: str — key from MODEL_CATALOG (e.g. "gemma3_12b")
            - engine: str — "mlx" | "ollama" | "llama_cpp"
    """
    # ── Monkey-patch input() so existing interactive functions don't hang ──
    # The existing installer functions (_download_ollama_model, etc.) call
    # input() for interactive prompts. In headless mode we auto-respond:
    #   - "[1/2]:" prompts → "1" (first option = "download now")
    #   - "(S/n):" prompts → "y" (yes, proceed)
    #   - "Press Enter" prompts → "" (just continue)
    _original_input = builtins.input

    def _auto_input(prompt=""):
        prompt_str = str(prompt)
        if "[1/" in prompt_str or "[1-" in prompt_str:
            response = "1"
        else:
            response = "y"
        print(f"  [auto] {response}", flush=True)
        return response

    builtins.input = _auto_input

    try:
        _run_headless_inner(config)
    finally:
        builtins.input = _original_input


# ═══════════════════════════════════════════════════════════════════════════
# FAÇADE HELPERS — each absorbs one logical block of _run_headless_inner
# ═══════════════════════════════════════════════════════════════════════════

def _parse_headless_config(config):
    """Extract and validate all config fields from the JSON payload."""
    lang = config.get("lang", "ca")
    project_root = Path(config.get("path", str(PROJECT_ROOT)))
    model_key = config.get("model_key")
    engine = config.get("engine", "ollama")
    skip_model_download = bool(config.get("skip_model_download", False))
    reinstall_mode = config.get("reinstall_mode", DEFAULT_REINSTALL_MODE)
    if reinstall_mode not in VALID_REINSTALL_MODES:
        _log.warning(
            "Invalid reinstall_mode=%r, falling back to default %r",
            reinstall_mode, DEFAULT_REINSTALL_MODE,
        )
        reinstall_mode = DEFAULT_REINSTALL_MODE
    return lang, project_root, model_key, engine, skip_model_download, reinstall_mode


def _apply_reinstall_if_needed(project_root, reinstall_mode):
    """Apply reinstall mode if an existing installation is detected."""
    if not (project_root.exists() and detect_existing_install(project_root)):
        return
    # Bug 7 fix — reinstall handling with 3 modes (wipe/overwrite/backup).
    # If we detect an existing installation, we apply the user-chosen mode
    # before doing anything else. Without this, the same API key, vectors
    # and knowledge base would be recycled (and the KB would be duplicated
    # by re-ingestion).
    try:
        summary = apply_reinstall_mode(project_root, reinstall_mode)
        _log.info(
            "Reinstall mode=%s applied: removed=%d backup_dir=%s",
            summary["mode"], len(summary["removed"]), summary["backup_dir"],
        )
        if summary.get("backup_dir"):
            print(f"[BACKUP] {summary['backup_dir']}", flush=True)
        print(f"[REINSTALL] mode={reinstall_mode}", flush=True)
    except Exception as e:
        _log.error(f"Reinstall mode application failed: {e}\n{traceback.format_exc()}")
        print(f"[ERROR] Reinstall mode failed: {e}", flush=True)
        sys.exit(1)


def _configure_i18n(lang):
    """Set language environment variable and update i18n module."""
    os.environ["NEXE_LANG"] = lang
    import installer.installer_i18n as i18n
    i18n.LANG = lang


def _resolve_model_config(model_key, engine, skip_model_download):
    """Find model in catalog, build model_config dict, apply engine fallback.

    Returns (model_config, engine, skip_model_download, selected_model).
    Calls sys.exit(1) if model_key is provided but not found or has no artifact.
    """
    if not model_key:
        # "Continue without model" — install without downloading any model
        _log.info("No model selected — installing without model download")
        return None, engine, True, None

    selected_model = None
    for category in MODEL_CATALOG.values():
        for model in category:
            if model["key"] == model_key:
                selected_model = model
                break
        if selected_model:
            break

    if not selected_model:
        print(f"[ERROR] Model not found: {model_key}", flush=True)
        sys.exit(1)

    # Build model_config (same structure as select_model() returns)
    model_id = _model_id_for_engine(selected_model, engine)
    if not model_id:
        for fallback_engine in ("mlx", "ollama", "llama_cpp"):
            model_id = _model_id_for_engine(selected_model, fallback_engine)
            if model_id:
                _log.warning(
                    "Engine '%s' not available for model '%s', falling back to '%s'",
                    engine, selected_model["key"], fallback_engine,
                )
                engine = fallback_engine
                break

    if not model_id:
        print(f"[ERROR] No downloadable artifact found for model: {model_key}", flush=True)
        sys.exit(1)

    model_config = {
        "size": _get_model_size(model_key),
        "engine": engine,
        "id": model_id,
        "name": selected_model["name"],
        "disk_size": f"~{selected_model['disk_gb']} GB",
        "ram": selected_model["ram_gb"],
        "prompt_tier": selected_model.get("prompt_tier", "full"),
        "chat_format": selected_model.get("chat_format", "chatml"),
    }
    return model_config, engine, skip_model_download, selected_model


def _run_env_setup(project_root, hw, engine):
    """Steps 1+2: create virtual environment and install dependencies.

    Returns python_path. Calls sys.exit(1) on failure.
    """
    emit(1, "running", "Creating virtual environment...")
    _log.info("Starting setup_environment (venv + deps)")
    venv_path = project_root / "venv"
    venv_existed = venv_path.exists()

    def _monitor_venv():
        """Poll for venv creation to transition step 1→2 in the GUI."""
        if venv_existed:
            emit(1, "done")
            emit(2, "running", "Installing dependencies...")
            return
        for _ in range(120):  # up to 60s
            time.sleep(0.5)
            if venv_path.exists():
                emit(1, "done")
                emit(2, "running", "Installing dependencies...")
                return

    monitor = threading.Thread(target=_monitor_venv, daemon=True)
    monitor.start()

    try:
        python_path = setup_environment(project_root, hw, engine=engine)
        monitor.join(timeout=1)
        _log.info(f"setup_environment complete, python_path={python_path}")
        emit(1, "done")
        emit(2, "done")
    except SystemExit as e:
        _log.error(f"setup_environment failed with sys.exit({e.code})\n{traceback.format_exc()}")
        emit(1, "error", "Environment setup failed")
        emit(2, "error", "Environment setup failed")
        print(f"[ERROR] Environment setup failed (exit {e.code})", flush=True)
        sys.exit(1)
    except Exception as e:
        _log.error(f"setup_environment failed: {e}\n{traceback.format_exc()}")
        emit(1, "error", str(e)[:200])
        emit(2, "error", str(e)[:200])
        print(f"[ERROR] {e}", flush=True)
        sys.exit(1)

    return python_path


def _run_model_download(model_config, engine, skip_model_download, model_key, selected_model, hw, project_root, python_path):
    """Step 3: download the selected model.

    Returns (model_ok, model_config). model_config may be updated when MLX
    falls back to Ollama so the correct engine is recorded in .env.
    Bug 28 fix — if skip_model_download, records model in .env but downloads nothing.
    """
    if skip_model_download or model_config is None:
        emit(3, "running", "Skipping model download (user requested)")
        _log.info(
            "Skipping model download; model_key=%s",
            model_key or "none",
        )
        emit(3, "done", "Skipped (no model selected or download deferred)")
        print("[MODEL_SKIPPED] download deferred", flush=True)
        return True, model_config

    emit(3, "running", f"Downloading {model_config['name']} ({engine})...")
    _log.info(f"Starting model download: {model_config['name']} engine={engine} id={model_config['id']}")
    try:
        if engine == "ollama":
            if not ensure_ollama_installed(headless=True):
                _log.warning("Ollama installation failed or skipped")
                emit(3, "error", "Ollama not available")
                raise RuntimeError("Ollama installation failed — cannot download model")
            _download_ollama_model(model_config, headless=True)
        elif engine == "llama_cpp":
            _download_gguf_model(model_config, project_root, headless=True)
        elif engine == "mlx":
            if not hw.get("has_metal", False):
                _log.warning("MLX requested but Metal not available — falling back to ollama")
                emit(3, "running", "MLX not available (no Metal), falling back to Ollama...")
                # Rebuild model_config for ollama fallback
                ollama_id = selected_model.get("ollama")
                if ollama_id:
                    model_config = {**model_config, "engine": "ollama", "id": ollama_id}
                    engine = "ollama"
                    if not ensure_ollama_installed(headless=True):
                        raise RuntimeError("Ollama installation failed — cannot download model")
                    _download_ollama_model(model_config, headless=True)
                else:
                    raise RuntimeError(f"No Ollama fallback for model {model_config['name']}")
            else:
                _download_mlx_model(model_config, project_root, python_path, headless=True)
        _log.info("Model download complete")
        emit(3, "done")
        return True, model_config
    except Exception as e:
        _log.error(f"Model download failed: {e}\n{traceback.format_exc()}")
        emit(3, "error", str(e)[:200])
        print(f"[ERROR] Model download failed: {e}", flush=True)
        return False, model_config


def _run_config_step(project_root, model_config):
    """Step 4: generate .env and report API key to GUI. Exits on failure."""
    emit(4, "running", "Generating configuration...")
    _log.info("Starting .env generation")
    try:
        generate_env_file(project_root, model_config)

        # Read back the API key to send to GUI
        env_file = project_root / ".env"
        api_key = ""
        try:
            for line in env_file.read_text().splitlines():
                if line.startswith("NEXE_PRIMARY_API_KEY="):
                    api_key = line.split("=", 1)[1].strip()
                    break
        except Exception:  # nosec B110: best-effort .env read for GUI report; missing key is tolerated (logged below as 'not found')
            pass
        if api_key:
            print(f"[API_KEY] {api_key}", flush=True)

        _log.info(f"Config generated, api_key={'set' if api_key else 'not found'}")
        emit(4, "done")
    except Exception as e:
        _log.error(f"Config generation failed: {e}\n{traceback.format_exc()}")
        emit(4, "error", str(e)[:200])
        print(f"[ERROR] Config generation failed: {e}", flush=True)
        sys.exit(1)


def _setup_nexe_wrapper(project_root, python_path):
    """Create the nexe wrapper script and attempt a global symlink. Returns nexe_cmd."""
    nexe_wrapper = project_root / "nexe"
    with open(nexe_wrapper, "w") as f:
        f.write("#!/bin/bash\n")
        f.write(f'export PYTHONPATH="$PYTHONPATH:{project_root}"\n')
        f.write(f'{python_path} -m core.cli "$@"\n')
    nexe_wrapper.chmod(0o755)

    global_symlink_created = False
    try:
        symlink_path = Path("/usr/local/bin/nexe")
        if symlink_path.exists() or symlink_path.is_symlink():
            symlink_path.unlink()
        symlink_path.symlink_to(nexe_wrapper)
        global_symlink_created = True
    except Exception:  # nosec B110: /usr/local/bin symlink failure (typically PermissionError) is non-fatal — the local ./nexe wrapper still works
        pass

    return "nexe" if global_symlink_created else "./nexe"


def _run_embeddings_step(project_root, python_path):
    """Step 6: download the embedding model into the project venv."""
    emit(6, "running", "Downloading embedding model...")
    _log.info("Starting embeddings download")
    try:
        # Read embedding model from server.toml (SSOT)
        _emb_model = "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"
        try:
            import toml as _toml  # type: ignore[import-untyped]  # toml lacks stubs (deprecated); kept for write path
            _srv_cfg = _toml.load(PROJECT_ROOT / "personality" / "server.toml")
            _emb_model = _srv_cfg.get("plugins", {}).get("models", {}).get("embedding", _emb_model)
        except Exception:  # nosec B110: best-effort server.toml read; on failure keep default embedding model literal
            pass
        emb_env = {**os.environ, "TRANSFORMERS_VERBOSITY": "error"}
        subprocess.run([  # nosec B603: python_path absolute venv Path; -c is literal headless probe; _emb_model from server.toml
            str(python_path), "-c",
            "import sys; "
            "from fastembed import TextEmbedding; "
            "model = TextEmbedding(sys.argv[1]); "
            "print('Embeddings downloaded')",
            _emb_model,
        ], check=True, capture_output=True, text=True, env=emb_env, timeout=300)
        _log.info("Embeddings download complete")
        emit(6, "done")
    except Exception as e:
        _log.error(f"Embeddings download failed: {e}\n{traceback.format_exc()}")
        emit(6, "error", str(e)[:200])
        # Non-fatal — will auto-download on first use


def _run_knowledge_step(project_root, python_path, lang):
    """Step 7: ingest knowledge base files into the embedded Qdrant collection."""
    emit(7, "running", "Processing knowledge base...")
    _log.info(f"Starting knowledge ingestion, lang={lang}")
    knowledge_dir = project_root / "knowledge"
    _ingest_dir = knowledge_dir / lang if (knowledge_dir / lang).is_dir() else knowledge_dir
    knowledge_files = (
        list(_ingest_dir.glob("*.md"))
        + list(_ingest_dir.glob("*.txt"))
        + list(_ingest_dir.glob("*.pdf"))
    )
    knowledge_files = [f for f in knowledge_files if not f.name.startswith('.')]

    if knowledge_files:
        try:
            # Q5.5 reopened (2026-04-08): ingestion via embedded QdrantClient.
            # Previously we launched an external Qdrant server binary at
            # 'storage/qdrant/' that nothing connected to. Ingestion now goes
            # directly through the embedded path at 'storage/vectors/' via
            # core/qdrant_pool.py.
            ingest_env = {**os.environ, "NEXE_LANG": lang, "TRANSFORMERS_VERBOSITY": "error"}
            # NO check=True — if the subprocess fails we want to see stderr,
            # not a generic CalledProcessError. We capture stdout/stderr and
            # write them to the installer log for visibility (bug 2026-04-14:
            # ingest only processed IDENTITY.md and exited 0 with no trace).
            result = subprocess.run([  # nosec B603: python_path absolute venv Path; project_root is Path(__file__)-derived embedded as literal in -c script
                str(python_path), "-c",
                f"import sys; sys.path.insert(0, '{project_root}'); "
                "import asyncio; "
                "from core.ingest.ingest_knowledge import ingest_knowledge; "
                # F7: explicit target_collection — corporate docs go to
                # nexe_documentation, not user_knowledge.
                "asyncio.run(ingest_knowledge(quiet=False, target_collection='nexe_documentation'))"
            ], check=False, capture_output=True, text=True, timeout=300, env=ingest_env)

            if result.stdout:
                _log.info(f"[ingest stdout]\n{result.stdout.strip()}")
            if result.stderr:
                _log.warning(f"[ingest stderr]\n{result.stderr.strip()}")
            if result.returncode != 0:
                _log.error(f"Ingest subprocess returned non-zero: {result.returncode}")
                raise RuntimeError(f"ingest_knowledge exited {result.returncode}")

            # Mark as ingested
            marker = project_root / "storage" / ".knowledge_ingested"
            marker.touch()
        except Exception as e:
            _log.error(f"Knowledge ingestion failed: {e}\n{traceback.format_exc()}")
            print(f"Knowledge ingestion warning: {e}", flush=True)

    _log.info("Knowledge ingestion complete")
    emit(7, "done")


def _register_macos_app(project_root, config):
    """Register Nexe.app at install path for Dock + Login Items. Remove legacy orphan."""
    # Register Nexe.app at <install_path>/Nexe.app for Dock + Login Items (macOS only).
    #
    # Bug #19d (v1.0 release): Nexe.app lives ONLY inside the install directory.
    # Earlier versions copied a second bundle to `/Applications/Nexe.app` to give
    # users a visible icon there. That copy had no Python code next to it, so its
    # Swift launcher resolved to the external marker file (fragile) and failed
    # when the marker was stale — producing an app that silently did nothing.
    # Single source of truth avoids drift and dead copies.
    #
    # Retrocompat: the uninstaller still cleans `/Applications/Nexe.app` if a
    # pre-fix installation left one behind.
    install_nexe_app = project_root / "Nexe.app"
    nexe_app_ready = install_nexe_app.exists()
    # Always persist the project-root marker so the Swift launcher can
    # resolve the install dir from any launch path.
    if nexe_app_ready:
        try:
            _write_project_marker(install_nexe_app, project_root)
        except Exception as e:
            _log.warning(f"Could not write project_root marker: {e}")

    # Clean up legacy `/Applications/Nexe.app` from previous installs —
    # it is always an orphan (no venv next to it) after the #19d fix.
    # Guard: if the user chose `/Applications` as the install root
    # (bare — headless CLI only, the GUI wizard forces `server-nexe`
    # suffix via DestinationView), `install_nexe_app` resolves to the
    # SAME path as `legacy_app` and a naive rmtree would wipe the
    # bundle we just installed.
    legacy_app = Path("/Applications/Nexe.app")
    try:
        same_target = legacy_app.resolve() == install_nexe_app.resolve()
    except Exception:
        same_target = False
    if legacy_app.exists() and not same_target:
        try:
            import shutil
            shutil.rmtree(legacy_app)
            _log.info("Removed legacy /Applications/Nexe.app orphan")
        except Exception as e:
            _log.warning(f"Could not remove legacy /Applications/Nexe.app: {e}")

    # Login Items — point at the canonical install-dir Nexe.app.
    # The Swift wizard owns the user's checkbox choice; with
    # --no-login-item it skips this call to avoid duplicates.
    skip_login_item = bool(config.get("skip_login_item", False))
    if skip_login_item:
        _log.info("Login Items: skipped (managed by GUI wizard)")
    elif nexe_app_ready:
        try:
            subprocess.run([  # nosec B603 B607: install_nexe_app is project_root-derived Path (controlled); osascript via PATH (macOS-only headless installer)
                "osascript", "-e",
                f'tell application "System Events" to make login item at end '
                f'with properties {{path:"{install_nexe_app}", hidden:true}}'
            ], capture_output=True, timeout=10)
            _log.info("Nexe added to Login Items at %s", install_nexe_app)
        except Exception as e:
            _log.warning(f"Could not add to Login Items: {e}")
    else:
        _log.warning("Skipping Login Items setup: %s missing", install_nexe_app)

    # F6: headless notice — NexeTray.app (system tray) is not installed
    print(
        "[INFO] Headless mode: NexeTray.app (menu-bar icon) has not been installed. "
        "The server will auto-start on login (Login Item). "
        "To add the tray icon, use the GUI installer.",
        flush=True,
    )
    _log.info("Headless mode: NexeTray.app not installed (no tray icon)")


def _run_headless_inner(config):
    """Inner implementation (with input() already patched)."""
    lang, project_root, model_key, engine, skip_model_download, reinstall_mode = _parse_headless_config(config)
    _apply_reinstall_if_needed(project_root, reinstall_mode)
    _configure_i18n(lang)
    model_config, engine, skip_model_download, selected_model = _resolve_model_config(
        model_key, engine, skip_model_download
    )

    # Detect hardware (quiet — prints are captured by GUI log)
    hw = detect_hardware()

    # Create storage folders
    for folder in ("storage/cache", "storage/logs", "storage/models", "storage/vectors"):
        (project_root / folder).mkdir(parents=True, exist_ok=True)

    # ── Step 1+2: Virtual environment + dependencies ─────────────────────
    python_path = _run_env_setup(project_root, hw, engine)

    # ── Step 3: Download model ──────────────────────────────────────────
    _model_ok, model_config = _run_model_download(
        model_config, engine, skip_model_download, model_key, selected_model, hw, project_root, python_path
    )

    # ── Step 4: Configure .env ──────────────────────────────────────────
    _run_config_step(project_root, model_config)

    # Clean module cache
    cache_file = project_root / "personality" / ".module_cache.json"
    if cache_file.exists():
        cache_file.unlink()

    # ── Step 5: Qdrant (embedded, no external download) ─────────────────
    # Q5.5 reopened (2026-04-08): Qdrant is now embedded via QdrantClient(path=)
    # in core/qdrant_pool.py. No external binary required. The step is kept for
    # compatibility with the GUI Swift wizard (7 steps expected) but is a no-op.
    emit(5, "running", "Qdrant embedded (no external download needed)...")
    _log.info("Qdrant is embedded (storage/vectors via QdrantClient path=), skipping external binary")
    emit(5, "done")

    nexe_cmd = _setup_nexe_wrapper(project_root, python_path)

    # Create knowledge folder
    (project_root / "knowledge").mkdir(exist_ok=True)

    # ── Step 6: Download embeddings ─────────────────────────────────────
    _run_embeddings_step(project_root, python_path)

    # ── Step 7: Process knowledge base ──────────────────────────────────
    _run_knowledge_step(project_root, python_path, lang)

    # Write COMMANDS.md
    _write_commands_file(project_root, nexe_cmd, model_config)

    if platform.system() == "Darwin":
        _register_macos_app(project_root, config)
    else:
        _log.info("Non-macOS platform: skipping .app registration and Login Items")

    print(f"[LOG] {LOG_FILE}", flush=True)
    if _model_ok:
        _log.info("Installation completed successfully")
        print("[DONE]", flush=True)
    else:
        _log.warning("Installation completed but model download failed")
        print("[DONE_PARTIAL] model_download_failed", flush=True)


def _get_model_size(model_key):
    """Find which size category a model belongs to."""
    for size, models in MODEL_CATALOG.items():
        for m in models:
            if m["key"] == model_key:
                return size
    return "medium"


# ═══════════════════════════════════════════════════════════════════════════
# ENTRY POINT — reads JSON config from stdin
# ═══════════════════════════════════════════════════════════════════════════
def _parse_cli_overrides(argv):
    """Parse minimal CLI overrides — currently only --reinstall-mode.

    Bug 7 — allows a headless user to choose the reinstall mode without
    having to pass it via JSON. The JSON still takes precedence if provided.
    """
    overrides = {}
    it = iter(argv)
    for arg in it:
        if arg == "--reinstall-mode":
            try:
                overrides["reinstall_mode"] = next(it)
            except StopIteration:
                print("[ERROR] --reinstall-mode requires a value", flush=True)
                sys.exit(2)
        elif arg.startswith("--reinstall-mode="):
            overrides["reinstall_mode"] = arg.split("=", 1)[1]
        elif arg == "--skip-model-download":
            # Bug 28 fix — CLI flag to proactively skip the model download
            # (not only on error). The chosen model is recorded in .env
            # for manual download later via `nexe model pull <name>`.
            overrides["skip_model_download"] = True
        elif arg == "--no-login-item":
            # The Swift wizard manages Login Items according to the user's
            # checkbox; with this flag, install_headless skips adding it
            # to avoid duplicates.
            overrides["skip_login_item"] = True
    if "reinstall_mode" in overrides:
        if overrides["reinstall_mode"] not in VALID_REINSTALL_MODES:
            print(
                f"[ERROR] Invalid --reinstall-mode={overrides['reinstall_mode']!r}. "
                f"Valid: {', '.join(VALID_REINSTALL_MODES)}",
                flush=True,
            )
            sys.exit(2)
    return overrides


if __name__ == "__main__":
    try:
        cli_overrides = _parse_cli_overrides(sys.argv[1:])
        raw = sys.stdin.read()
        config = json.loads(raw)
        # CLI overrides applied if the JSON does not include them
        for k, v in cli_overrides.items():
            config.setdefault(k, v)
        _log.info(f"Starting installation with config: {json.dumps(config, ensure_ascii=False)}")
        # Emit log path immediately so GUI can always show it on failures.
        print(f"[LOG] {LOG_FILE}", flush=True)
        run_headless(config)
    except json.JSONDecodeError as e:
        _log.error(f"Invalid JSON config: {e}")
        print(f"[ERROR] Invalid JSON config: {e}", flush=True)
        sys.exit(1)
    except KeyboardInterrupt:
        _log.info("Installation cancelled by user")
        print("[ERROR] Cancelled by user", flush=True)
        sys.exit(130)
    except Exception as e:
        _log.error(f"Fatal error: {e}\n{traceback.format_exc()}")
        print(f"[LOG] {LOG_FILE}", flush=True)
        print(f"[ERROR] {e}", flush=True)
        sys.exit(1)
