"""
────────────────────────────────────
Server Nexe
Location: installer/installer_ollama_install.py
Description: Installation of the Ollama runtime (app/binary) on macOS and
             Linux, plus the helpers that locate an existing binary or a
             bundled offline zip inside the DMG.

This module was split out of ``installer_setup_models.py`` on 2026-04-23
to keep the parent under the 500-line rule after the F4.1 SHA256
verification code landed. The model-download functions stay in the old
file; anything that concerns *bringing Ollama to the system* lives here.
────────────────────────────────────
"""

from __future__ import annotations

import os
import platform
import subprocess  # nosec B404: subprocess required for Ollama macOS app install (curl + xattr + open) and Linux install script; usage validated below
import time
import shutil
from pathlib import Path

from .installer_display import (
    BOLD, CYAN, DIM, RESET,
    print_step, print_success, print_warn,
)
from .installer_i18n import t


def _find_ollama() -> str:
    """Locate the ollama binary — app bundles run with a minimal PATH."""
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
    return "ollama"  # fallback — let subprocess raise FileNotFoundError


def _find_bundle_ollama_zip():
    """Locate ``Ollama-darwin.zip`` inside the DMG bundle resources.

    Same lookup precedence as ``_find_bundle_resources()`` in
    ``installer_setup_env.py``:

    1. ``NEXE_BUNDLE_RESOURCES`` environment variable.
    2. Co-located ``InstallNexe.app`` in the repo root (dev / gitoss).
    3. Mounted DMG volumes under ``/Volumes/``.
    """
    candidates = []

    env_path = os.environ.get("NEXE_BUNDLE_RESOURCES")
    if env_path:
        candidates.append(Path(env_path) / "ollama" / "Ollama-darwin.zip")

    project_root = Path(__file__).parent.parent
    candidates.append(
        project_root / "InstallNexe.app" / "Contents" / "Resources"
        / "ollama" / "Ollama-darwin.zip"
    )

    volumes = Path("/Volumes")
    if volumes.is_dir():
        try:
            for vol in volumes.iterdir():
                candidates.append(
                    vol / "InstallNexe.app" / "Contents" / "Resources"
                    / "ollama" / "Ollama-darwin.zip"
                )
        except PermissionError:
            pass

    for c in candidates:
        if c.is_file():
            return c
    return None


def ensure_ollama_installed(headless: bool = False) -> bool:
    """Install Ollama if it isn't on the host already.

    In ``headless=True`` mode (CLI / Swift wizard) the interactive
    confirmation is skipped because the user already chose a model that
    requires Ollama. On macOS we extract ``Ollama.app`` into
    ``/Applications/`` and launch it (first launch registers the CLI at
    ``/usr/local/bin/ollama``); on Linux we pipe the official install
    script.
    """
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
    if system == "linux":
        return _install_ollama_linux()
    print_warn(f"Ollama auto-install not supported on {system}")
    print(f"  {DIM}{t('ollama_install_manual')}{RESET}")
    return False


def _install_ollama_macos() -> bool:
    """Install ``Ollama.app`` on macOS, preferring the DMG bundle when present.

    Lookup order:
      1. Bundled zip at ``InstallNexe.app/Contents/Resources/ollama/Ollama-darwin.zip``
         (placed there by ``build-ollama-bundle.sh``; the DMG install is
         then 100 % offline).
      2. Online download from ``ollama.com/download/Ollama-darwin.zip``.

    Post-extract we strip quarantine so Gatekeeper does not block the
    launch, open the app (which registers the CLI on first run), and poll
    for the binary to appear at ``/usr/local/bin/ollama``.
    """
    import tempfile
    import zipfile

    url = "https://ollama.com/download/Ollama-darwin.zip"
    dest = Path("/Applications/Ollama.app")

    try:
        bundle_zip = _find_bundle_ollama_zip()
        if bundle_zip:
            print("  📦 Ollama offline: instal·lant des del bundle...")
            zip_path = str(bundle_zip)
        else:
            print("  📥 Downloading Ollama for macOS...")
            tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
            zip_path = tmp.name
            tmp.close()
            result = subprocess.run(  # nosec B603,B607: url is literal "https://ollama.com/download/Ollama-darwin.zip"; zip_path is tempfile mktemp; curl via PATH
                ["curl", "-fSL", "-o", zip_path, url],
                timeout=300, capture_output=True,
            )
            if result.returncode != 0:
                print_warn(t('ollama_install_failed'))
                print(f"  {CYAN}Download: {url}{RESET}")
                return False

        print("  📦 Installing to /Applications/Ollama.app...")
        with zipfile.ZipFile(zip_path, 'r') as zf:
            zf.extractall("/Applications/")

        if not bundle_zip and os.path.isfile(zip_path):
            os.unlink(zip_path)

        subprocess.run(  # nosec B603,B607: dest is hardcoded /Applications/Ollama.app Path; xattr via PATH
            ["xattr", "-rd", "com.apple.quarantine", str(dest)],
            capture_output=True,
        )

        print("  🚀 Starting Ollama...")
        subprocess.run(["open", "-a", "Ollama"], capture_output=True)  # nosec B603,B607: literal `open -a Ollama`; macOS open via PATH

        for _ in range(15):
            time.sleep(2)
            ollama_bin = _find_ollama()
            if os.path.isfile(ollama_bin):
                print_success(t('ollama_installed'))
                return True

        print_warn("Ollama.app installed but CLI not yet available — try again in a moment")
        return True

    except subprocess.TimeoutExpired:
        print_warn("Ollama download timed out (>5 min)")
        return False
    except Exception as e:
        print_warn(f"{t('ollama_install_failed')}: {e}")
        print(f"  {CYAN}{url}{RESET}")
        return False


def _install_ollama_linux() -> bool:
    """Install Ollama on Linux via the official install script."""
    try:
        print(f"  {DIM}curl -fsSL https://ollama.com/install.sh | sh{RESET}")
        result = subprocess.run(  # nosec B603,B607: literal Ollama install command per upstream docs (supply chain trust = ollama.com); bash via PATH
            ["bash", "-c", "curl -fsSL https://ollama.com/install.sh | sh"],
            timeout=180,
        )
        if result.returncode == 0:
            print_success(t('ollama_installed'))
            return True
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


__all__ = [
    "_find_ollama",
    "_find_bundle_ollama_zip",
    "ensure_ollama_installed",
    "_install_ollama_macos",
    "_install_ollama_linux",
]
