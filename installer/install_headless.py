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
import subprocess
import sys
import time
import threading
import traceback
from datetime import datetime
from pathlib import Path

# Import root: parent of installer/ package (works from both app bundle and repo)
_import_root = str(Path(__file__).parent.parent.resolve())
if _import_root not in sys.path:
    sys.path.insert(0, _import_root)

# Project root — prefer NEXE_PROJECT_ROOT env var (set by launcher)
_env_root = os.environ.get("NEXE_PROJECT_ROOT")
PROJECT_ROOT = Path(_env_root).resolve() if _env_root else Path(__file__).parent.parent.resolve()

from installer.installer_hardware import detect_hardware
from installer.installer_catalog_data import MODEL_CATALOG
from installer.installer_setup_env import setup_environment
from installer.installer_setup_config import generate_env_file
from installer.installer_setup_qdrant import download_qdrant
from installer.installer_setup_models import (
    ensure_ollama_installed,
    _download_ollama_model,
    _download_gguf_model,
    _download_mlx_model,
)
from installer.installer_finalize import _write_commands_file

# ═══════════════════════════════════════════════════════════════════════════
# INSTALLATION LOG — persistent file for debugging failures
# ═══════════════════════════════════════════════════════════════════════════
LOG_DIR = PROJECT_ROOT / "storage" / "logs"
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
    """Persist the real install path inside Nexe.app for launcher lookup."""
    marker = app_bundle / "Contents" / "Resources" / "project_root.txt"
    marker.parent.mkdir(parents=True, exist_ok=True)
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
    # The existing installer functions (download_qdrant, _download_ollama_model,
    # etc.) call input() for interactive prompts. In headless mode we auto-respond:
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


def _run_headless_inner(config):
    """Inner implementation (with input() already patched)."""
    lang = config.get("lang", "ca")
    project_root = Path(config.get("path", str(PROJECT_ROOT)))
    model_key = config.get("model_key")
    engine = config.get("engine", "ollama")

    # Set language for i18n
    os.environ["NEXE_LANG"] = lang
    import installer.installer_i18n as i18n
    i18n.LANG = lang

    # Find the model in the catalog
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

    # Detect hardware (quiet — prints are captured by GUI log)
    hw = detect_hardware()

    # Create storage folders
    for folder in ("storage/cache", "storage/logs", "storage/models", "storage/vectors"):
        (project_root / folder).mkdir(parents=True, exist_ok=True)

    # ── Step 1+2: Virtual environment + dependencies ─────────────────────
    # setup_environment() handles both: creates venv if needed, then installs deps.
    # We monitor the venv dir to transition from step 1 → step 2.
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

    # ── Step 3: Download model ──────────────────────────────────────────
    emit(3, "running", f"Downloading {model_config['name']} ({engine})...")
    _log.info(f"Starting model download: {model_config['name']} engine={engine} id={model_config['id']}")
    try:
        if engine == "ollama":
            ensure_ollama_installed()
            _download_ollama_model(model_config)
        elif engine == "llama_cpp":
            _download_gguf_model(model_config, project_root)
        elif engine == "mlx":
            _download_mlx_model(model_config, project_root, python_path)
        _log.info("Model download complete")
        emit(3, "done")
    except Exception as e:
        _log.error(f"Model download failed: {e}\n{traceback.format_exc()}")
        emit(3, "error", str(e)[:200])
        print(f"[ERROR] Model download failed: {e}", flush=True)
        _model_ok = False
        # Continue — model can be downloaded later
    else:
        _model_ok = True

    # ── Step 4: Configure .env ──────────────────────────────────────────
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
        except Exception:
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

    # Clean module cache
    cache_file = project_root / "personality" / ".module_cache.json"
    if cache_file.exists():
        cache_file.unlink()

    # ── Step 5: Download Qdrant ─────────────────────────────────────────
    emit(5, "running", "Downloading Qdrant vector database...")
    _log.info("Starting Qdrant download")
    try:
        download_qdrant(project_root, hw)
        _log.info("Qdrant download complete")
        emit(5, "done")
    except Exception as e:
        _log.error(f"Qdrant download failed: {e}\n{traceback.format_exc()}")
        emit(5, "error", str(e)[:200])
        # Non-fatal — RAG will not work but system still functions

    # Create nexe wrapper script
    nexe_wrapper = project_root / "nexe"
    with open(nexe_wrapper, "w") as f:
        f.write("#!/bin/bash\n")
        f.write(f'export PYTHONPATH="$PYTHONPATH:{project_root}"\n')
        f.write(f'{python_path} -m core.cli "$@"\n')
    nexe_wrapper.chmod(0o755)

    # Try global symlink
    global_symlink_created = False
    try:
        symlink_path = Path("/usr/local/bin/nexe")
        if symlink_path.exists() or symlink_path.is_symlink():
            symlink_path.unlink()
        symlink_path.symlink_to(nexe_wrapper)
        global_symlink_created = True
    except Exception:
        pass

    nexe_cmd = "nexe" if global_symlink_created else "./nexe"

    # Create knowledge folder
    knowledge_dir = project_root / "knowledge"
    knowledge_dir.mkdir(exist_ok=True)

    # ── Step 6: Download embeddings ─────────────────────────────────────
    emit(6, "running", "Downloading embedding model...")
    _log.info("Starting embeddings download")
    try:
        emb_env = {**os.environ, "TRANSFORMERS_VERBOSITY": "error"}
        subprocess.run([
            str(python_path), "-c",
            "from sentence_transformers import SentenceTransformer; "
            "model = SentenceTransformer('paraphrase-multilingual-mpnet-base-v2'); "
            "print('Embeddings downloaded')"
        ], check=True, capture_output=False, text=True, env=emb_env, timeout=300)
        _log.info("Embeddings download complete")
        emit(6, "done")
    except Exception as e:
        _log.error(f"Embeddings download failed: {e}\n{traceback.format_exc()}")
        emit(6, "error", str(e)[:200])
        # Non-fatal — will auto-download on first use

    # ── Step 7: Process knowledge base ──────────────────────────────────
    emit(7, "running", "Processing knowledge base...")
    _log.info(f"Starting knowledge ingestion, lang={lang}")
    _ingest_dir = knowledge_dir / lang if (knowledge_dir / lang).is_dir() else knowledge_dir
    knowledge_files = (
        list(_ingest_dir.glob("*.md"))
        + list(_ingest_dir.glob("*.txt"))
        + list(_ingest_dir.glob("*.pdf"))
    )
    knowledge_files = [f for f in knowledge_files if not f.name.startswith('.')]

    qdrant_process = None
    if knowledge_files:
        try:
            qdrant_bin = project_root / "qdrant"
            qdrant_storage = project_root / "storage" / "qdrant"
            qdrant_storage.mkdir(parents=True, exist_ok=True)

            env = os.environ.copy()
            env["QDRANT__STORAGE__STORAGE_PATH"] = str(qdrant_storage)
            env["QDRANT__SERVICE__HTTP_PORT"] = "6333"
            env["QDRANT__SERVICE__DISABLE_TELEMETRY"] = "true"

            qdrant_process = subprocess.Popen(
                [str(qdrant_bin), "--disable-telemetry"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=env,
            )
            time.sleep(3)

            ingest_env = {**os.environ, "NEXE_LANG": lang, "TRANSFORMERS_VERBOSITY": "error"}
            subprocess.run([
                str(python_path), "-c",
                f"import sys; sys.path.insert(0, '{project_root}'); "
                "import asyncio; "
                "from core.ingest.ingest_knowledge import ingest_knowledge; "
                "asyncio.run(ingest_knowledge(quiet=False))"
            ], check=True, capture_output=False, text=True, timeout=300, env=ingest_env)

            # Mark as ingested
            marker = project_root / "storage" / ".knowledge_ingested"
            marker.touch()

            qdrant_process.terminate()
            qdrant_process.wait(timeout=5)
        except Exception as e:
            _log.error(f"Knowledge ingestion failed: {e}\n{traceback.format_exc()}")
            print(f"Knowledge ingestion warning: {e}", flush=True)
            if qdrant_process is not None:
                try:
                    qdrant_process.terminate()
                except Exception:
                    pass

    _log.info("Knowledge ingestion complete")
    emit(7, "done")

    # Write COMMANDS.md
    _write_commands_file(project_root, nexe_cmd, model_config)

    # Copy Nexe.app to /Applications (so the user has an icon to launch)
    nexe_app_src = project_root / "Nexe.app"
    nexe_app_dest = Path("/Applications/Nexe.app")
    nexe_app_ready = False
    if nexe_app_src.exists():
        try:
            import shutil
            if nexe_app_dest.exists():
                shutil.rmtree(nexe_app_dest)
            shutil.copytree(nexe_app_src, nexe_app_dest)
            _write_project_marker(nexe_app_dest, project_root)
            nexe_app_ready = True
            _log.info(f"Nexe.app copied to /Applications")
        except PermissionError:
            _log.warning("Could not copy Nexe.app to /Applications (permission denied)")
        except Exception as e:
            _log.warning(f"Could not copy Nexe.app to /Applications: {e}")

    # Add to Login Items (auto-start on boot)
    if nexe_app_ready:
        try:
            subprocess.run([
                "osascript", "-e",
                'tell application "System Events" to make login item at end '
                'with properties {path:"/Applications/Nexe.app", hidden:true}'
            ], capture_output=True, timeout=10)
            _log.info("Nexe added to Login Items")
        except Exception as e:
            _log.warning(f"Could not add to Login Items: {e}")
    else:
        _log.warning("Skipping Login Items setup: /Applications/Nexe.app unavailable")

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
if __name__ == "__main__":
    try:
        raw = sys.stdin.read()
        config = json.loads(raw)
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
