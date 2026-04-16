"""
────────────────────────────────────
Server Nexe
Location: installer/installer_setup_models.py
Description: Model downloads (Ollama/GGUF/MLX) and Ollama installation.
────────────────────────────────────
"""

import os
import sys
import shutil
import subprocess

from .installer_display import (
    APP_LOGO, clear,
    GREEN, RED, YELLOW, CYAN, BOLD, DIM, RESET,
    print_step, print_success, print_warn,
)
from .installer_i18n import t


def _find_ollama() -> str:
    """Find ollama binary — app bundles have minimal PATH."""
    found = shutil.which("ollama")
    if found:
        return found
    for path in [
        "/usr/local/bin/ollama",
        "/opt/homebrew/bin/ollama",
        os.path.expanduser("~/bin/ollama"),
        "/Applications/Ollama.app/Contents/Resources/ollama",
    ]:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return "ollama"  # fallback, let subprocess raise FileNotFoundError


def _show_manual_instructions(model, engine):
    """Show manual download instructions."""
    print(f"\n{YELLOW}{'─'*60}{RESET}")
    print(f"{BOLD}📥 {t('download_instructions')}{RESET}")
    print(f"{YELLOW}{'─'*60}{RESET}\n")

    if engine == "ollama":
        print(f"{t('install_ollama_first')}")
        print(f"  {DIM}curl -fsSL https://ollama.com/install.sh | sh{RESET}\n")
        print(f"{t('to_download_ollama')}")
        print(f"  {CYAN}ollama pull {model['id']}{RESET}\n")
    elif engine == "llama_cpp":
        print(f"{t('download_gguf_instructions')}")
        print(f"  {CYAN}curl -L -o storage/models/{model['id'].split('/')[-1]} {model['id']}{RESET}\n")
    else:
        print(f"{t('to_download_mlx')}")
        print(f"  {CYAN}python -c \"from mlx_lm import load; load('{model['id']}')\" {RESET}\n")

    print(f"{t('after_download')}")
    print(f"  {CYAN}./nexe chat{RESET}\n")

    print(f"{DIM}💡 {t('manual_install_note')}{RESET}")


def ensure_ollama_installed(headless=False):
    """
    Ensure Ollama is installed (universal fallback for LLM inference).

    In headless/GUI mode (headless=True), skips the interactive confirmation
    and proceeds directly with the install — the user already chose a model
    that requires Ollama via the wizard UI.

    On macOS: downloads Ollama-darwin.zip, extracts Ollama.app to /Applications/,
    and launches it (which registers the CLI at /usr/local/bin/ollama).
    On Linux: uses the official install.sh script.
    """
    import platform

    ollama_bin = _find_ollama()
    if os.path.isfile(ollama_bin):
        print_success(t('ollama_installed'))
        return True

    print_step(f"{BOLD}{t('installing_ollama')}{RESET}")

    if not headless:
        confirm = input(f"{t('ollama_install_confirm')} {t('yes_no')}: ").lower()
        if confirm == 'n':
            print_warn(t('ollama_install_skipped'))
            print(f"  {DIM}{t('ollama_install_manual')}{RESET}")
            return False

    system = platform.system().lower()

    if system == "darwin":
        return _install_ollama_macos()
    elif system == "linux":
        return _install_ollama_linux()
    else:
        print_warn(f"Ollama auto-install not supported on {system}")
        print(f"  {DIM}{t('ollama_install_manual')}{RESET}")
        return False


def _install_ollama_macos():
    """Install Ollama.app on macOS from bundle (offline) or download (online).

    Lookup order:
    1. Bundled zip at InstallNexe.app/Contents/Resources/ollama/Ollama-darwin.zip
       (placed there by build-ollama-bundle.sh → DMG install is 100% offline).
    2. Online download from ollama.com/download/Ollama-darwin.zip.

    Extracts to /Applications/Ollama.app, removes quarantine, launches the app
    (which registers the CLI at /usr/local/bin/ollama on first run).
    """
    import tempfile
    import zipfile

    url = "https://ollama.com/download/Ollama-darwin.zip"
    dest = Path("/Applications/Ollama.app")

    try:
        # 1. Try bundled zip (offline install from DMG)
        bundle_zip = _find_bundle_ollama_zip()
        if bundle_zip:
            print(f"  📦 Ollama offline: instal·lant des del bundle...")
            zip_path = str(bundle_zip)
        else:
            # 2. Download from internet
            print(f"  📥 Downloading Ollama for macOS...")
            tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
            zip_path = tmp.name
            tmp.close()
            result = subprocess.run(
                ["curl", "-fSL", "-o", zip_path, url],
                timeout=300, capture_output=True,
            )
            if result.returncode != 0:
                print_warn(t('ollama_install_failed'))
                print(f"  {CYAN}Download: {url}{RESET}")
                return False

        # Extract to /Applications/
        print(f"  📦 Installing to /Applications/Ollama.app...")
        with zipfile.ZipFile(zip_path, 'r') as zf:
            zf.extractall("/Applications/")

        # Clean up downloaded zip (not the bundled one)
        if not bundle_zip and os.path.isfile(zip_path):
            os.unlink(zip_path)

        # Remove quarantine so Gatekeeper doesn't block it
        subprocess.run(
            ["xattr", "-rd", "com.apple.quarantine", str(dest)],
            capture_output=True,
        )

        # Launch Ollama.app — registers CLI at /usr/local/bin/ollama
        print(f"  🚀 Starting Ollama...")
        subprocess.run(["open", "-a", "Ollama"], capture_output=True)

        # Wait for CLI to become available (first launch setup)
        import time
        for _ in range(15):
            time.sleep(2)
            ollama_bin = _find_ollama()
            if os.path.isfile(ollama_bin):
                print_success(t('ollama_installed'))
                return True

        # App installed but CLI not yet — still counts as success
        print_warn("Ollama.app installed but CLI not yet available — try again in a moment")
        return True

    except subprocess.TimeoutExpired:
        print_warn("Ollama download timed out (>5 min)")
        return False
    except Exception as e:
        print_warn(f"{t('ollama_install_failed')}: {e}")
        print(f"  {CYAN}{url}{RESET}")
        return False


def _find_bundle_ollama_zip():
    """Find Ollama-darwin.zip in the DMG bundle resources.

    Same lookup logic as _find_bundle_resources() in installer_setup_env.py:
    1. NEXE_BUNDLE_RESOURCES env var
    2. Co-located InstallNexe.app (dev/gitoss)
    3. Mounted DMG volumes (/Volumes/*)
    """
    candidates = []

    env_path = os.environ.get("NEXE_BUNDLE_RESOURCES")
    if env_path:
        candidates.append(Path(env_path) / "ollama" / "Ollama-darwin.zip")

    # Co-located (dev mode)
    project_root = Path(__file__).parent.parent
    candidates.append(project_root / "InstallNexe.app" / "Contents" / "Resources" / "ollama" / "Ollama-darwin.zip")

    # Mounted DMG volumes
    volumes = Path("/Volumes")
    if volumes.is_dir():
        try:
            for vol in volumes.iterdir():
                candidates.append(vol / "InstallNexe.app" / "Contents" / "Resources" / "ollama" / "Ollama-darwin.zip")
        except PermissionError:
            pass

    for c in candidates:
        if c.is_file():
            return c
    return None


def _install_ollama_linux():
    """Install Ollama on Linux via official install script."""
    try:
        print(f"  {DIM}curl -fsSL https://ollama.com/install.sh | sh{RESET}")
        result = subprocess.run(
            ["bash", "-c", "curl -fsSL https://ollama.com/install.sh | sh"],
            timeout=180,
        )
        if result.returncode == 0:
            print_success(t('ollama_installed'))
            return True
        else:
            print_warn(t('ollama_install_failed'))
            print(f"  {CYAN}curl -fsSL https://ollama.com/install.sh | sh{RESET}")
            return False
    except subprocess.TimeoutExpired:
        print_warn("Ollama install timed out (>3 min)")
        return False
    except Exception as e:
        print_warn(f"{t('ollama_install_failed')}: {e}")
        print(f"  {CYAN}curl -fsSL https://ollama.com/install.sh | sh{RESET}")
        return False


def _download_ollama_model(model_config, headless=False):
    """Download Ollama model immediately after selection."""
    clear()
    print(APP_LOGO)

    model_id = model_config['id']
    print(f"\n{BOLD}📦 {t('downloading_model')}{RESET}")
    print(f"   Model: {CYAN}{model_config['name']}{RESET}")
    print(f"   Ollama ID: {CYAN}{model_id}{RESET}")
    print(f"   {t('engine_ollama_label')}")
    print()

    if headless:
        choice = "1"  # Always download in headless mode
    else:
        print(f"{BOLD}{t('download_options')}{RESET}\n")
        print(f"  {CYAN}1.{RESET} {t('option_download_now')}")
        print(f"  {CYAN}2.{RESET} {t('option_manual_later')}")
        print()

        try:
            choice = input(f"{BOLD}[1/2]:{RESET} ").strip()
        except (EOFError, OSError):
            choice = "1"  # Default to download if no stdin

    if choice == "1":
        try:
            ollama_bin = _find_ollama()
            print(f"\n{CYAN}[1/3]{RESET} {t('ollama_checking')}")
            result = subprocess.run([ollama_bin, "list"], capture_output=True, text=True)
            if result.returncode != 0:
                print(f"{YELLOW}[...]{RESET} {t('starting_ollama')}")
                subprocess.Popen([ollama_bin, "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                # Wait for Ollama to be ready (max 15s)
                import time
                import socket
                for _ in range(30):
                    try:
                        with socket.create_connection(("localhost", 11434), timeout=0.5):
                            break
                    except (ConnectionRefusedError, OSError):
                        time.sleep(0.5)
                else:
                    print(f"{YELLOW}[WARN]{RESET} Ollama may not be ready yet")

            print(f"\n{CYAN}[2/3]{RESET} {t('downloading_model_progress')}")
            print(f"      {DIM}{ollama_bin} pull {model_id}{RESET}\n")

            process = subprocess.Popen(
                [ollama_bin, "pull", model_id],
                stdout=sys.stdout,
                stderr=sys.stderr
            )
            return_code = process.wait()

            if return_code != 0:
                raise subprocess.CalledProcessError(return_code, "ollama pull")

            print(f"\n{CYAN}[3/4]{RESET} {t('verifying_download')}")
            result = subprocess.run([ollama_bin, "list"], capture_output=True, text=True)
            model_base = model_id.split(":")[0]
            if model_base in result.stdout or model_id in result.stdout:
                print_success(t('model_downloaded_ok').format(id=model_id))
            else:
                print_warn(t('model_not_in_list'))
                print(f"  {DIM}{t('run_ollama_list')}{RESET}")

            print(f"\n{CYAN}[4/4]{RESET} {t('downloading_embeddings_step')}")
            print(f"      {DIM}{ollama_bin} pull nomic-embed-text{RESET}\n")

            embed_process = subprocess.Popen(
                [ollama_bin, "pull", "nomic-embed-text"],
                stdout=sys.stdout,
                stderr=sys.stderr
            )
            embed_return = embed_process.wait()

            if embed_return == 0:
                print_success(t('embeddings_downloaded'))
            else:
                print_warn(t('embeddings_failed'))
                print(f"  {DIM}{t('embeddings_manual')}{RESET}")

        except subprocess.CalledProcessError as e:
            print_warn(f"{t('download_failed')} (code: {e.returncode})")
            if headless:
                raise
            _show_manual_instructions(model_config, "ollama")
        except FileNotFoundError:
            print_warn(t('ollama_not_found'))
            if headless:
                raise
            _show_manual_instructions(model_config, "ollama")
    else:
        _show_manual_instructions(model_config, "ollama")
        print(f"\n{YELLOW}⚠️  Model {model_id} NOT downloaded. Before starting nexe, run:{RESET}")
        print(f"  {CYAN}ollama pull {model_id}{RESET}")
        print(f"  {CYAN}ollama pull nomic-embed-text{RESET}")
        print(f"\n{GREEN}{t('download_skipped')}{RESET}")

    if not headless:
        try:
            input(f"\n{DIM}[{t('press_enter')}]{RESET}")
        except (EOFError, OSError):
            pass


def _download_gguf_model(model_config, project_root, headless=False):
    """Download GGUF model immediately after selection."""
    clear()
    print(APP_LOGO)

    print(f"\n{BOLD}📦 {t('downloading_model')}{RESET}")
    print(f"   Model: {CYAN}{model_config['name']}{RESET}")
    print(f"   {t('engine_gguf_label')}")
    print()

    if headless:
        choice = "1"  # Always download in headless mode
    else:
        print(f"{BOLD}{t('download_options')}{RESET}\n")
        print(f"  {CYAN}1.{RESET} {t('option_download_now')}")
        print(f"  {CYAN}2.{RESET} {t('option_manual_later')}")
        print()

        try:
            choice = input(f"{BOLD}[1/2]:{RESET} ").strip()
        except (EOFError, OSError):
            choice = "1"  # Default to download if no stdin

    if choice == "1":
        try:
            models_dir = project_root / "storage" / "models"
            models_dir.mkdir(parents=True, exist_ok=True)
            filename = model_config['id'].split('/')[-1]
            output_path = models_dir / filename

            print(f"\n{CYAN}[...]{RESET} {t('downloading_file').format(filename=filename)}")
            print(f"   {DIM}{model_config['id']}{RESET}")

            subprocess.run([
                "curl", "-L", "--progress-bar",
                "-o", str(output_path),
                model_config['id']
            ], check=True)

            # Verify file was actually downloaded and has content
            if not output_path.exists() or output_path.stat().st_size == 0:
                raise RuntimeError(f"Downloaded file is empty or missing: {output_path}")

            print_success(t('download_success'))
            print(f"  📁 {output_path}")
        except subprocess.CalledProcessError as e:
            print_warn(t('download_failed'))
            if headless:
                raise
            _show_manual_instructions(model_config, "llama_cpp")
        except Exception as e:
            print_warn(f"{t('download_failed')}: {e}")
            if headless:
                raise
            _show_manual_instructions(model_config, "llama_cpp")
    else:
        _show_manual_instructions(model_config, "llama_cpp")
        print(f"\n{GREEN}{t('download_skipped')}{RESET}")

    if not headless:
        try:
            input(f"\n{DIM}[{t('press_enter')}]{RESET}")
        except (EOFError, OSError):
            pass


def _download_mlx_model(model_config, project_root, python_path, headless=False):
    """Download MLX model immediately after selection."""
    clear()
    print(APP_LOGO)

    model_id = model_config['id']
    model_name = model_id.split('/')[-1]

    print(f"\n{BOLD}📦 {t('downloading_model')}{RESET}")
    print(f"   Model: {CYAN}{model_config['name']}{RESET}")
    print(f"   HuggingFace ID: {CYAN}{model_id}{RESET}")
    print(f"   {t('engine_mlx_label')}")
    print()

    if headless:
        choice = "1"  # Always download in headless mode
    else:
        print(f"{BOLD}{t('download_options')}{RESET}\n")
        print(f"  {CYAN}1.{RESET} {t('option_download_now')}")
        print(f"  {CYAN}2.{RESET} {t('option_manual_later')}")
        print()

        try:
            choice = input(f"{BOLD}[1/2]:{RESET} ").strip()
        except (EOFError, OSError):
            choice = "1"  # Default to download if no stdin

    if choice == "1":
        try:
            models_dir = project_root / "storage" / "models"
            models_dir.mkdir(parents=True, exist_ok=True)
            local_model_path = models_dir / model_name

            if local_model_path.exists() and any(local_model_path.iterdir()):
                print(f"{GREEN}[OK]{RESET} {t('model_already_downloaded').format(path=local_model_path)}")
                if not headless:
                    try:
                        input(f"\n{DIM}[{t('press_enter')}]{RESET}")
                    except (EOFError, OSError):
                        pass
                return

            if not headless:
                clear()
                print(APP_LOGO)
                print(f"\n{RED}{BOLD}{t('download_warning_title').format(size=model_config['disk_size'])}{RESET}\n")
                print(f"  {YELLOW}1.{RESET} {t('download_warning_power')}")
                print(f"  {YELLOW}2.{RESET} {t('download_warning_sleep')}")
                print(f"  {YELLOW}3.{RESET} {t('download_warning_wifi')}")
                print(f"\n  {DIM}• {t('download_warning_time')}{RESET}")
                print(f"  {DIM}• {t('download_warning_resume')}{RESET}\n")

                try:
                    input(f"{GREEN}▶ {t('download_ready')} [Enter]:{RESET} ")
                except (EOFError, OSError):
                    pass

            print(f"\n{CYAN}[1/2]{RESET} {t('downloading_mlx_step')}")
            print(f"      {DIM}{t('mlx_destination').format(path=local_model_path)}{RESET}\n")

            download_script = f'''
from huggingface_hub import snapshot_download
import time

max_retries = 3
for attempt in range(max_retries):
    try:
        snapshot_download(
            repo_id="{model_id}",
            local_dir="{local_model_path}",
            local_dir_use_symlinks=False,
            resume_download=True,
            max_workers=4
        )
        print("Download complete!")
        break
    except Exception as e:
        if attempt < max_retries - 1:
            print(f"Download interrupted, retrying in 5 seconds... (attempt {{attempt+1}}/{{max_retries}})")
            time.sleep(5)
        else:
            raise e
'''
            process = subprocess.Popen(
                [str(python_path), "-c", download_script],
                stdout=sys.stdout,
                stderr=sys.stderr,
                env={**os.environ, "PYTHONPATH": str(project_root)}
            )
            return_code = process.wait()

            if return_code == 0:
                print_success(t('mlx_downloaded_ok').format(path=local_model_path))

                print(f"\n{CYAN}[2/2]{RESET} {t('mlx_validating')}")
                config_file = local_model_path / "config.json"
                if not config_file.exists():
                    print_warn(t('mlx_config_missing').format(path=local_model_path))
                    print(f"{DIM}{t('mlx_may_have_issues')}{RESET}")
                else:
                    print(f"{GREEN}✓{RESET} {t('mlx_validated_ok')}")
            else:
                raise subprocess.CalledProcessError(return_code, "mlx_download")

        except Exception as e:
            print(f"\n{YELLOW}{t('download_failed_resume')}{RESET}")
            print(f"{DIM}Error: {str(e)[:200]}{RESET}")
            print(f"{DIM}{t('partial_files_preserved')}{RESET}\n")
            if headless:
                raise
            _show_manual_instructions(model_config, "mlx")
    else:
        _show_manual_instructions(model_config, "mlx")
        print(f"\n{YELLOW}{t('mlx_no_model_warning')}{RESET}")
        print(f"   {t('mlx_fallback_ollama')}")
        print(f"\n{GREEN}{t('download_skipped')}{RESET}")

    if not headless:
        try:
            input(f"\n{DIM}[{t('press_enter')}]{RESET}")
        except (EOFError, OSError):
            pass
