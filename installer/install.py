"""
────────────────────────────────────
Server Nexe
Location: installer/install.py
Description: Installer orchestrator — coordinates all installation steps.
────────────────────────────────────
"""

import os
import re
import shutil
import sys
import subprocess
from datetime import datetime
from pathlib import Path

from .installer_display import (
    APP_LOGO, clear,
    GREEN, RED, YELLOW, CYAN, BOLD, DIM, RESET,
    print_step, print_error,
)
from .installer_i18n import select_language, t, get_lang
from .installer_hardware import detect_hardware
from .installer_catalog import select_model, MODEL_CATALOG
from .installer_setup_env import setup_environment
from .installer_setup_config import generate_env_file
from .installer_setup_models import (
    ensure_ollama_installed,
    _download_ollama_model,
    _download_gguf_model,
    _download_mlx_model,
)
from .installer_finalize import show_final_summary
from .installer_reinstall import (
    REINSTALL_MODE_BACKUP,
    REINSTALL_MODE_OVERWRITE,
    REINSTALL_MODE_WIPE,
    apply_reinstall_mode,
    detect_existing_install,
)


class _TeeWriter:
    """Duplicates stdout to a log file, stripping ANSI codes for the file."""
    _ANSI_RE = re.compile(r'\x1b\[[0-9;]*m')

    def __init__(self, log_path):
        self._terminal = sys.stdout
        self._log = open(log_path, 'w', encoding='utf-8')
        self._log.write(f"# Nexe Installer Log — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        self.log_path = log_path

    def write(self, text):
        self._terminal.write(text)
        self._log.write(self._ANSI_RE.sub('', text))
        self._log.flush()

    def flush(self):
        self._terminal.flush()
        self._log.flush()

    def close(self):
        self._log.close()
        sys.stdout = self._terminal

    def __getattr__(self, name):
        return getattr(self._terminal, name)


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _resolve_install_root(project_root: Path) -> Path:
    """Linux only: if the project is inside a downloads/temp dir, copy to
    ~/.local/share/nexe/ and use that as the real install root."""
    if not sys.platform.startswith("linux"):
        return project_root
    home = Path.home()
    suspect_parents = [
        home / "Baixades", home / "Downloads", home / "Descargas",
        home / "Téléchargements", home / "tmp", Path("/tmp"),  # nosec B108: not a temp file destination — element of an allow-list to detect a bad install location
    ]
    if not any(_is_relative_to(project_root, p) for p in suspect_parents):
        return project_root
    return home / ".local" / "share" / "nexe"


def _perform_linux_relocation(source_root: Path, project_root: Path) -> None:
    """Linux: copy source_root to project_root (outside Downloads/tmp) and chdir."""
    print(f"\n{YELLOW}[Linux]{RESET} Directori de descàrregues detectat.")
    print(f"  Instal·lant a: {CYAN}{project_root}{RESET}\n")
    if project_root.exists():
        shutil.rmtree(project_root)
    shutil.copytree(
        source_root, project_root,
        ignore=shutil.ignore_patterns("venv", "__pycache__", "*.pyc", ".git"),
    )
    os.chdir(project_root)
    print(f"{GREEN}[OK]{RESET} Fitxers copiats a {project_root}\n")


def _setup_install_log(project_root: Path):
    """Create storage/logs/, start TeeWriter and redirect stdout. Return (tee, log_path)."""
    log_dir = project_root / "storage" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"install_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    tee = _TeeWriter(log_path)
    sys.stdout = tee
    return tee, log_path


def _confirm_proceed(tee) -> bool:
    """Ask for user confirmation. Close the tee and return False if cancelled."""
    confirm = input(f"\n{BOLD}{t('proceed_install')}{RESET} {t('yes_no')}: ").strip().lower()
    if confirm not in ('y', 'yes', 's', 'si', 'sí'):
        print("Cancelled.")
        tee.close()
        return False
    return True


def _handle_reinstall_or_clean(project_root: Path) -> bool:
    """Handle interactive reinstall or venv cleanup. Return False if the install should abort."""
    if detect_existing_install(project_root):
        print(f"\n{YELLOW}[!] Instal·lació existent detectada a:{RESET} {project_root}")
        print(f"\n  {CYAN}1){RESET} Esborra-ho tot (.env, storage/, knowledge/, venv)")
        print(f"  {CYAN}2){RESET} Sobreescriu sistema preservant dades (manté .env, storage/, knowledge/)")
        print(f"  {CYAN}3){RESET} Backup automàtic + instal·lació neta {DIM}[per defecte]{RESET}")
        choice = input(f"\n{BOLD}Tria [1/2/3]:{RESET} ").strip()
        mode_map = {
            "1": REINSTALL_MODE_WIPE,
            "2": REINSTALL_MODE_OVERWRITE,
            "3": REINSTALL_MODE_BACKUP,
            "": REINSTALL_MODE_BACKUP,
        }
        mode = mode_map.get(choice, REINSTALL_MODE_BACKUP)
        try:
            summary = apply_reinstall_mode(project_root, mode)
            print(f"{GREEN}[OK]{RESET} Mode aplicat: {mode}")
            if summary.get("backup_dir"):
                print(f"  📦 Backup creat a: {summary['backup_dir']}")
            if summary.get("removed"):
                print(f"  🧹 {len(summary['removed'])} elements esborrats")
        except Exception as e:
            print_error(f"Reinstall mode failed: {e}")
            return False
    else:
        venv_path = project_root / "venv"
        if venv_path.exists():
            print(f"\n{YELLOW}[CLEAN]{RESET} {t('cleaning_venv')}")
            shutil.rmtree(venv_path)
            print(f"{GREEN}[OK]{RESET} {t('venv_removed')}")
    return True


def _resolve_skip_model_config() -> dict:
    """Detect the first local Ollama model; if none found, fall back to Qwen3.5 2B."""
    detected = None
    try:
        import json as _json
        import urllib.request as _urlreq
        with _urlreq.urlopen("http://localhost:11434/api/tags", timeout=2) as _resp:  # nosec B310  # nosemgrep: dynamic-urllib-use-detected,insecure-urlopen — hardcoded localhost Ollama URL
            _data = _json.loads(_resp.read().decode("utf-8"))
            _models = _data.get("models", [])
            if _models:
                detected = _models[0].get("name")
    except Exception:
        detected = None

    if detected:
        print(f"\n{GREEN}✓{RESET} {DIM}Model Ollama detectat: {CYAN}{detected}{RESET}{DIM} — s'usarà com a default.{RESET}\n")
        return {
            "size": "small",
            "engine": "ollama",
            "id": detected,
            "name": detected,
            "disk_size": "(local)",
            "ram": 0,
            "prompt_tier": "full",
            "chat_format": "chatml",
        }
    else:
        print(f"\n{YELLOW}Cap model local detectat — instal·lant Qwen3.5 4B per defecte perquè el servidor arrenqui.{RESET}\n")
        _fallback = next(
            (m for m in MODEL_CATALOG["small"] if m.get("key") == "qwen35_4b"),
            MODEL_CATALOG["small"][0],
        )
        return {
            "size": "small",
            "engine": "ollama",
            "id": _fallback["ollama"],
            "name": _fallback["name"],
            "disk_size": f"~{_fallback['disk_gb']} GB",
            "ram": _fallback["ram_gb"],
            "prompt_tier": _fallback.get("prompt_tier", "small"),
            "chat_format": _fallback.get("chat_format", "chatml"),
        }


def _show_download_confirmation() -> None:
    """Show the download confirmation screen with battery warning."""
    clear()
    print(APP_LOGO)
    print(f"\n{BOLD}📦 {t('download_confirmation_title')}{RESET}\n")
    print(f"{DIM}{t('download_confirmation_text')}{RESET}\n")
    print(f"{YELLOW}{'─'*70}{RESET}")
    print(f"{YELLOW}{BOLD}⚠️  {t('laptop_warning')}{RESET}")
    print(f"{YELLOW}   • {t('download_warning_power')}{RESET}")
    print(f"{YELLOW}   • {t('download_warning_sleep')}{RESET}")
    print(f"{YELLOW}   • {t('download_warning_wifi')}{RESET}")
    print(f"{YELLOW}   • {t('download_warning_time')}{RESET}")
    print(f"{YELLOW}{'─'*70}{RESET}\n")
    input(f"{GREEN}{t('download_continue')}{RESET}")


def _create_storage_folders(project_root: Path) -> None:
    """Create the four subdirectories under storage/."""
    print_step(f"{BOLD}{t('preparing_data')}{RESET}")
    for folder in ("storage/cache", "storage/logs", "storage/models", "storage/vectors"):
        (project_root / folder).mkdir(parents=True, exist_ok=True)
        print(f"  ✅ {folder}/")


def _handle_mlx_engine(model_config: dict, project_root: Path, python_path: Path) -> None:
    """Verify Metal and download MLX, or offer Ollama fallback if Metal is unavailable."""
    metal_available = False
    try:
        result = subprocess.run(  # nosec B603: python_path is venv-derived absolute Path; -c argument is hardcoded literal Metal probe
            [str(python_path), "-c", "import mlx.core as mx; print(mx.metal.is_available())"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        metal_available = result.stdout.strip() == "True"
    except Exception:
        metal_available = False

    if not metal_available:
        clear()
        print(APP_LOGO)
        print(f"\n{RED}{t('metal_unavailable')}{RESET}\n")
        print(f"{DIM}{t('metal_needs_explanation')}{RESET}")
        print(f"{DIM}{t('metal_cannot_init')}{RESET}\n")
        print(f"{YELLOW}{t('mlx_fallback_options')}{RESET}\n")
        print(f"  {CYAN}1.{RESET} {t('switch_to_ollama_option')}")
        print(f"  {CYAN}2.{RESET} {t('abort_install_option')}\n")
        choice = input(f"{BOLD}{t('select_fallback_prompt')}{RESET} ").strip()
        if choice == "1":
            selected_model = None
            for category in MODEL_CATALOG:
                for model in MODEL_CATALOG[category]:
                    if model.get("mlx") == model_config['id']:
                        selected_model = model
                        break
                if selected_model:
                    break
            if selected_model and selected_model.get("ollama"):
                model_config['engine'] = 'ollama'
                model_config['id'] = selected_model['ollama']
                print(f"\n{GREEN}✓{RESET} {t('switched_to_ollama_msg').format(id=model_config['id'])}\n")
                ensure_ollama_installed()
                _download_ollama_model(model_config)
            else:
                print_error(t('no_ollama_alternative'))
                sys.exit(1)
        else:
            print(f"\n{YELLOW}{t('installation_cancelled')}{RESET}")
            sys.exit(0)
    else:
        _download_mlx_model(model_config, project_root, python_path)


def _cleanup_module_cache(project_root: Path) -> None:
    """Delete .module_cache.json if it exists."""
    cache_file = project_root / "personality" / ".module_cache.json"
    if cache_file.exists():
        cache_file.unlink()
        print(f"  🧹 {t('module_cache_cleaned')}")
        print(f"     {DIM}{t('cache_explanation')}{RESET}")


def _create_nexe_wrapper(project_root: Path, python_path: Path) -> tuple:
    """Create the nexe script and attempt a global symlink. Return (wrapper_path, symlink_ok)."""
    nexe_wrapper = project_root / "nexe"
    with open(nexe_wrapper, "w") as f:
        f.write("#!/bin/bash\n")
        f.write(f"export PYTHONPATH=\"$PYTHONPATH:{project_root}\"\n")
        f.write(f"{python_path} -m core.cli \"$@\"\n")
    nexe_wrapper.chmod(0o755)
    print(f"  ✅ {t('executable_created')}")
    print(f"     {DIM}{t('executable_explanation')}{RESET}")

    global_symlink_created = False
    try:
        symlink_path = Path("/usr/local/bin/nexe")
        if symlink_path.exists() or symlink_path.is_symlink():
            symlink_path.unlink()
        symlink_path.symlink_to(nexe_wrapper)
        print(f"  ✅ {t('symlink_created')}")
        print(f"     {DIM}{t('symlink_global')}{RESET}")
        global_symlink_created = True
    except PermissionError:
        print(f"\n  {YELLOW}⚠️  {t('symlink_failed')}{RESET}")
        print(f"     {DIM}{t('symlink_manual')}{RESET}")
        print(f"     {CYAN}export PATH=\"$PATH:{project_root}\"{RESET}\n")
    except Exception as e:
        print(f"  {DIM}{t('symlink_not_created').format(error=str(e)[:50], path=project_root)}{RESET}")
    return nexe_wrapper, global_symlink_created


def _setup_knowledge_dir(project_root: Path) -> Path:
    """Create and return the knowledge/ directory."""
    print_step(f"{BOLD}{t('knowledge_folder_created')}{RESET}")
    knowledge_dir = project_root / "knowledge"
    knowledge_dir.mkdir(exist_ok=True)
    print(f"  ✅ {t('knowledge_dir_created')}")
    print(f"  {DIM}{t('knowledge_explanation')}{RESET}")
    return knowledge_dir


def _download_embeddings(project_root: Path, python_path: Path) -> None:
    """Ask for permission and download the embeddings model via fastembed."""
    print(f"\n{YELLOW}{'─'*60}{RESET}")
    info_text = t('embeddings_info').format(bold=BOLD, reset=RESET)
    print(info_text)
    print(f"{YELLOW}{'─'*60}{RESET}\n")

    confirm = input(f"{t('embeddings_download_prompt')} {t('yes_no')}: ").strip().lower()
    if confirm not in ('y', 'yes', 's', 'si', 'sí'):
        print(f"  {DIM}{t('embeddings_skipped')}{RESET}")
        return

    _emb_model = "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"
    try:
        import toml as _toml  # type: ignore[import-untyped]  # toml lacks stubs (deprecated); kept for write path
        _srv_cfg = _toml.load(project_root / "personality" / "server.toml")
        _emb_model = _srv_cfg.get("plugins", {}).get("models", {}).get("embedding", _emb_model)
    except Exception:  # nosec B110: best-effort server.toml read; on failure keep default embedding model literal
        pass

    print_step(f"{BOLD}{t('downloading_embeddings_step')} ({_emb_model})...{RESET}")
    print(f"  {DIM}{t('downloading_model_progress')}{RESET}\n")
    try:
        msg_start = t('embeddings_starting').replace("'", "\\'")
        msg_done = t('embeddings_done').replace("'", "\\'")
        emb_env = {**os.environ, "TRANSFORMERS_VERBOSITY": "error"}
        subprocess.run([  # nosec B603: python_path absolute venv Path; msg_start/msg_done are repo-owned i18n strings escaped via .replace; _emb_model from server.toml
            str(python_path), "-c",
            f"from fastembed import TextEmbedding; "
            f"import sys; "
            f"print('\\n  {msg_start}\\n'); "
            f"model = TextEmbedding(sys.argv[1]); "
            f"print('\\n  {msg_done}')",
            _emb_model,
        ], check=True, capture_output=False, env=emb_env)
        print(f"\n  {t('embeddings_downloaded_ok')}")
    except subprocess.CalledProcessError:
        print(f"  {YELLOW}{t('embeddings_download_error')}{RESET}")
        print(f"  {DIM}{t('embeddings_auto_download')}{RESET}")


def _ingest_knowledge_if_present(
    project_root: Path, python_path: Path, knowledge_dir: Path, lang: str
) -> None:
    """Ingest documents from knowledge/ if any are present."""
    _ingest_dir = knowledge_dir / lang if (knowledge_dir / lang).is_dir() else knowledge_dir
    knowledge_files = (
        list(_ingest_dir.glob("*.md"))
        + list(_ingest_dir.glob("*.txt"))
        + list(_ingest_dir.glob("*.pdf"))
    )
    knowledge_files = [f for f in knowledge_files if not f.name.startswith('.')]

    if knowledge_files:
        print_step(f"{BOLD}{t('processing_knowledge').format(n=len(knowledge_files))}{RESET}")
        print(f"  {DIM}{t('processing_knowledge_wait')}{RESET}\n")
        try:
            # Q5.5 reopened (2026-04-08): ingestion via embedded QdrantClient.
            # Previously we launched an external Qdrant server binary at
            # 'storage/qdrant/' that nothing connected to (ingest_knowledge
            # goes through the embedded path via core/qdrant_pool.py at
            # 'storage/vectors/'), leaving dead residue. Ingestion now goes
            # directly through the embedded path.
            ingest_env = {**os.environ, "NEXE_LANG": lang, "TRANSFORMERS_VERBOSITY": "error"}
            subprocess.run([  # nosec B603: python_path absolute venv Path; project_root is Path(__file__)-derived embedded as literal in -c script
                str(python_path), "-c",
                f"import sys; sys.path.insert(0, '{project_root}'); "
                "import asyncio; "
                "from core.ingest.ingest_knowledge import ingest_knowledge; "
                # F7: explicit target_collection so install-time docs go to
                # nexe_documentation (corporate know-how), not user_knowledge.
                f"asyncio.run(ingest_knowledge(quiet=False, target_collection='nexe_documentation'))"
            ], check=True, capture_output=False, text=True, timeout=300, env=ingest_env)
            print(f"\n  {t('knowledge_indexed_ok')}")
            marker_file = project_root / "storage" / ".knowledge_ingested"
            marker_file.touch()
        except subprocess.TimeoutExpired:
            print(f"  {YELLOW}⚠️  {t('ingest_timeout')}{RESET}")
        except Exception as e:
            print(f"  {YELLOW}⚠️  {t('ingest_error').format(error=str(e)[:200])}{RESET}")
            print(f"  {DIM}{t('ingest_auto_first_start')}{RESET}")
    else:
        print(f"  {DIM}📝 {t('no_knowledge_docs')}{RESET}")


def run_installer():
    """Run the interactive server-nexe installer (language, hardware, env, models, knowledge)."""
    # 1. Language selection
    select_language()

    clear()
    print(APP_LOGO)
    source_root = Path(__file__).parent.parent.resolve()
    project_root = _resolve_install_root(source_root)
    if project_root != source_root:
        _perform_linux_relocation(source_root, project_root)

    tee, log_path = _setup_install_log(project_root)

    # 2. Hardware detection
    hw = detect_hardware()

    # 3. Confirm installation
    if not _confirm_proceed(tee):
        return

    # 3.5. Reinstall handling — Bug 7 fix.
    if not _handle_reinstall_or_clean(project_root):
        return

    # 4. MODEL SELECTION FIRST - while user is engaged
    model_config = select_model(hw)

    # 4b. Skip: detect local Ollama model or fall back to Qwen3.5 2B.
    if model_config is None:
        model_config = _resolve_skip_model_config()

    # 4.5. Show download confirmation screen with power warning
    _show_download_confirmation()

    # 5. Create storage folders (needed for model download)
    _create_storage_folders(project_root)

    # 6. If Ollama selected: install Ollama and download model NOW
    engine = model_config.get("engine", "ollama")
    if engine == "ollama":
        ensure_ollama_installed()
        _download_ollama_model(model_config)
    elif engine == "llama_cpp":
        _download_gguf_model(model_config, project_root)

    # 7. Setup environment (pip install - takes time)
    python_path = setup_environment(project_root, hw, engine=model_config.get('engine', 'auto'))

    # 8. If MLX selected: validate Metal BEFORE downloading
    if engine == "mlx":
        _handle_mlx_engine(model_config, project_root, python_path)

    # 9. Generate .env with model config
    generate_env_file(project_root, model_config)

    # 10. Clean module cache
    # 11. (Q5.5 reopened 2026-04-08) — External Qdrant server binary removed.
    _cleanup_module_cache(project_root)

    # 12. Create nexe wrapper script + optional global symlink
    _, global_symlink_created = _create_nexe_wrapper(project_root, python_path)

    # 13. Create knowledge folder and inform user
    knowledge_dir = _setup_knowledge_dir(project_root)

    # 14. Download embedding model (with explanation and permission)
    _download_embeddings(project_root, python_path)

    # 15. Ingest knowledge documents if any exist
    lang = get_lang()
    _ingest_knowledge_if_present(project_root, python_path, knowledge_dir, lang)

    # 16. Final summary
    show_final_summary(model_config, project_root, global_symlink_created, lang)

    # Close install log
    print(f"\n  {DIM}📋 Install log: {log_path}{RESET}")
    tee.close()


def _applescript_quote(s: str) -> str:
    """Escape a Python string for a double-quoted AppleScript
    literal. Backslash first, then double-quote, exactly as AppleScript expects.
    Without this, a path containing `"` or `\\` either crashes the script or
    (if a future caller passes attacker-controlled paths) lets the attacker
    break out of the literal and append arbitrary AppleScript.
    """
    return s.replace("\\", "\\\\").replace('"', '\\"')


def add_login_item(app_path: str = "/Applications/Nexe.app") -> bool:
    """Add Nexe to macOS login items via osascript (legacy, universal).

    Equivalent to the Swift doAddLoginItem() in CompletionView.swift.
    Returns True on success, False on failure.
    """
    quoted = _applescript_quote(app_path)
    script = (
        f'tell application "System Events" to make login item at end '
        f'with properties {{path:"{quoted}", hidden:true}}'
    )
    result = subprocess.run(  # nosec B603: absolute path to system osascript; script built from app_path parameter (default /Applications/Nexe.app, escaped via _applescript_quote)
        ["/usr/bin/osascript", "-e", script],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def main():
    """Entry point with optional flags for headless / scripted use."""
    import argparse

    parser = argparse.ArgumentParser(description="Nexe installer")
    parser.add_argument(
        "--add-login-item",
        action="store_true",
        help="Add Nexe to macOS login items after installation (auto-start at login)",
    )
    parser.add_argument(
        "--app-path",
        default="/Applications/Nexe.app",
        help="Path to Nexe.app for the login item (default: /Applications/Nexe.app)",
    )
    args = parser.parse_args()

    run_installer()

    if args.add_login_item:
        ok = add_login_item(app_path=args.app_path)
        if ok:
            print(f"{GREEN}✅ Login item added: Nexe will start at login.{RESET}")
        else:
            print(f"{YELLOW}⚠️  Could not add login item. Add manually via System Settings → General → Login Items.{RESET}")


if __name__ == "__main__":
    main()
