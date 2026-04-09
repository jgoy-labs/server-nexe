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
import subprocess
import sys
import time
import threading
import traceback
import warnings
from datetime import datetime
from pathlib import Path

# Bug 3 (2026-04-06) — silenciar warnings de HuggingFace al log GUI.
# Abans `Please set a HF_TOKEN...` arribava a la GUI durant la instal·lació
# headless i confonia l'usuari. Ara desactivem telemetria, progress bars i
# els warnings específics abans que cap import HF els pugui emetre.
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

from installer.installer_hardware import detect_hardware
from installer.installer_catalog_data import MODEL_CATALOG
from installer.installer_setup_env import setup_environment
from installer.installer_setup_config import generate_env_file
from installer.installer_setup_models import (
    ensure_ollama_installed,
    _download_ollama_model,
    _download_gguf_model,
    _download_mlx_model,
)
from installer.installer_finalize import _write_commands_file
from installer.installer_reinstall import (
    DEFAULT_REINSTALL_MODE,
    VALID_REINSTALL_MODES,
    apply_reinstall_mode,
    detect_existing_install,
)

# ═══════════════════════════════════════════════════════════════════════════
# INSTALLATION LOG — persistent file for debugging failures
# ═══════════════════════════════════════════════════════════════════════════
# Dev #3 fix (Consultor passada 1, finding 3): abans LOG_DIR era
# PROJECT_ROOT/storage/logs, però `apply_reinstall_mode(BACKUP)` mou
# `storage/` a `.nexe-backups/` i el FileHandler queda escrivint a un
# fd mort. Ara els logs d'instal·lació viuen a ~/.nexe/install_logs/,
# fora del project_root, persistents entre instal·lacions i immunes
# al backup/wipe de l'installer.
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


def _run_headless_inner(config):
    """Inner implementation (with input() already patched)."""
    lang = config.get("lang", "ca")
    project_root = Path(config.get("path", str(PROJECT_ROOT)))
    model_key = config.get("model_key")
    engine = config.get("engine", "ollama")
    # Bug 28 fix — permet a l'usuari saltar proactivament la descarrega
    # del model. El model escollit queda registrat a `.env` (per a quan
    # l'usuari el descarregui manualment despres via `nexe model pull`),
    # pero NO toquem `storage/models/` i no consumim ample de banda.
    skip_model_download = bool(config.get("skip_model_download", False))
    reinstall_mode = config.get("reinstall_mode", DEFAULT_REINSTALL_MODE)
    if reinstall_mode not in VALID_REINSTALL_MODES:
        _log.warning(
            "Invalid reinstall_mode=%r, falling back to default %r",
            reinstall_mode, DEFAULT_REINSTALL_MODE,
        )
        reinstall_mode = DEFAULT_REINSTALL_MODE

    # Bug 7 fix — gestió de reinstal·lació amb 3 modes (wipe/overwrite/backup).
    # Si detectem una instal·lació prèvia, apliquem el mode escollit per
    # l'usuari abans de fer res més. Sense això, la mateixa API key, vectors
    # i knowledge base es reciclarien (i la KB es duplicaria per re-ingestió).
    if project_root.exists() and detect_existing_install(project_root):
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
    # Bug 28 fix — si l'usuari ha demanat saltar la descarrega, el
    # model queda registrat al .env (Step 4) pero no descarreguem res.
    # L'usuari pot fer `nexe model pull <name>` despres.
    if skip_model_download:
        emit(3, "running", "Skipping model download (user requested)")
        _log.info(
            "Skipping model download per skip_model_download=True; "
            "model_key=%s engine=%s id=%s will be registered in .env only",
            model_key, engine, model_config["id"],
        )
        emit(3, "done", "Skipped (model registered, download deferred)")
        print("[MODEL_SKIPPED] download deferred", flush=True)
        _model_ok = True  # treated as success — user opted out explicitly
    else:
        emit(3, "running", f"Downloading {model_config['name']} ({engine})...")
        _log.info(f"Starting model download: {model_config['name']} engine={engine} id={model_config['id']}")
        try:
            if engine == "ollama":
                if not ensure_ollama_installed():
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
                        if not ensure_ollama_installed():
                            raise RuntimeError("Ollama installation failed — cannot download model")
                        _download_ollama_model(model_config, headless=True)
                    else:
                        raise RuntimeError(f"No Ollama fallback for model {model_config['name']}")
                else:
                    _download_mlx_model(model_config, project_root, python_path, headless=True)
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

    # ── Step 5: Qdrant (embedded, no external download) ─────────────────
    # Q5.5 reobert (2026-04-08): Qdrant ara és embedded via QdrantClient(path=)
    # a core/qdrant_pool.py. Cap binari extern necessari. L'step es manté per
    # compatibilitat amb la GUI Swift wizard (7 steps esperats) però és no-op.
    emit(5, "running", "Qdrant embedded (no external download needed)...")
    _log.info("Qdrant is embedded (storage/vectors via QdrantClient path=), skipping external binary")
    emit(5, "done")

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

    if knowledge_files:
        try:
            # Q5.5 reobert (2026-04-08): ingestió via embedded QdrantClient.
            # Abans arrencàvem un binari Qdrant servidor extern a 'storage/qdrant/'
            # que ningú connectava. Ara la ingestió va directament per embedded
            # a 'storage/vectors/' via core/qdrant_pool.py.
            ingest_env = {**os.environ, "NEXE_LANG": lang, "TRANSFORMERS_VERBOSITY": "error"}
            subprocess.run([
                str(python_path), "-c",
                f"import sys; sys.path.insert(0, '{project_root}'); "
                "import asyncio; "
                "from core.ingest.ingest_knowledge import ingest_knowledge; "
                # F7: explicit target_collection — corporate docs go to
                # nexe_documentation, not user_knowledge.
                "asyncio.run(ingest_knowledge(quiet=False, target_collection='nexe_documentation'))"
            ], check=True, capture_output=False, text=True, timeout=300, env=ingest_env)

            # Mark as ingested
            marker = project_root / "storage" / ".knowledge_ingested"
            marker.touch()
        except Exception as e:
            _log.error(f"Knowledge ingestion failed: {e}\n{traceback.format_exc()}")
            print(f"Knowledge ingestion warning: {e}", flush=True)

    _log.info("Knowledge ingestion complete")
    emit(7, "done")

    # Write COMMANDS.md
    _write_commands_file(project_root, nexe_cmd, model_config)

    # Copy Nexe.app to /Applications and add to Login Items (macOS only)
    if platform.system() == "Darwin":
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
    else:
        _log.info("Non-macOS platform: skipping .app copy and Login Items")

    # F6: avís headless — no s'instal·la NexeTray.app (tray de sistema)
    if platform.system() == "Darwin":
        print(
            "[INFO] Headless mode: NexeTray.app (menu-bar icon) has not been installed. "
            "The server will auto-start on login (Login Item). "
            "To add the tray icon, use the GUI installer.",
            flush=True,
        )
        _log.info("Headless mode: NexeTray.app not installed (no tray icon)")

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

    Bug 7 — permet a un usuari headless triar el mode de reinstal·lació
    sense haver de fer-ho via JSON. El JSON segueix manant si també l'aporta.
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
            # Bug 28 fix — flag CLI per saltar la descarrega del model
            # de forma proactiva (no nomes en cas d'error). El model
            # escollit queda registrat al .env per a descarrega manual
            # posterior via `nexe model pull <name>`.
            overrides["skip_model_download"] = True
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
        # CLI overrides aplicats si el JSON no els porta
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
