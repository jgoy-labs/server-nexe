"""
────────────────────────────────────
Server Nexe
Location: installer/installer_setup_qdrant.py
Description: Qdrant binary download and macOS quarantine management.

DEPRECATED (v0.8.5): Qdrant now runs in embedded mode (QdrantClient(path=)).
No external binary needed. This module is kept for backwards compatibility
with existing installations that still use the external binary.
New installations should use NEXE_QDRANT_PATH=storage/vectors (default).
────────────────────────────────────
"""

import subprocess
from pathlib import Path

from .installer_display import (
    BLUE, GREEN, CYAN, BOLD, DIM, RESET,
    print_step, print_success, print_warn,
)
from .installer_i18n import t


def download_qdrant(project_root, hw):
    """Download Qdrant binary for the current platform."""
    import platform
    import tarfile

    qdrant_bin = project_root / "qdrant"
    if qdrant_bin.exists():
        print_success(t('qdrant_exists'))
        return True

    # Show informative explanation and ask for permission
    print(f"\n{BOLD}{'─'*60}{RESET}")
    info_text = t('qdrant_download_info').format(bold=BOLD, reset=RESET)
    print(info_text)
    print(f"{BOLD}{'─'*60}{RESET}\n")

    confirm = input(f"{t('qdrant_download_prompt')} {t('yes_no')}: ").strip().lower()
    if confirm not in ('y', 'yes', 's', 'si', 'sí'):
        print(f"  {DIM}{t('qdrant_skipped')}{RESET}")
        return False

    print_step(f"{BOLD}{t('downloading_qdrant')}{RESET}")
    print(f"  {DIM}{t('qdrant_explanation')}{RESET}")

    # Determine platform
    system = platform.system().lower()
    machine = platform.machine().lower()

    if system == "darwin":
        if "arm" in machine or "aarch64" in machine:
            asset_name = "qdrant-aarch64-apple-darwin.tar.gz"
        else:
            asset_name = "qdrant-x86_64-apple-darwin.tar.gz"
    elif system == "linux":
        if "arm" in machine or "aarch64" in machine:
            asset_name = "qdrant-aarch64-unknown-linux-gnu.tar.gz"
        else:
            asset_name = "qdrant-x86_64-unknown-linux-gnu.tar.gz"
    else:
        print_warn(f"Platform {system}/{machine} not supported for auto-download")
        return False

    try:
        import logging
        import urllib.request
        import urllib.error
        import json

        QDRANT_FALLBACK_VERSION = "v1.17.0"  # Known working version (updated 2026-03-17)

        try:
            api_url = "https://api.github.com/repos/qdrant/qdrant/releases/latest"
            with urllib.request.urlopen(api_url, timeout=10) as response:
                release_data = json.loads(response.read().decode())
        except (urllib.error.URLError, urllib.error.HTTPError) as e:
            logging.getLogger(__name__).warning("GitHub API failed (%s), using fallback version %s", e, QDRANT_FALLBACK_VERSION)
            release_data = {"tag_name": QDRANT_FALLBACK_VERSION}

        download_url = None
        for asset in release_data.get("assets", []):
            if asset["name"] == asset_name:
                download_url = asset["browser_download_url"]
                break

        if not download_url:
            # Construct URL from tag (fallback or asset not found)
            tag = release_data.get("tag_name", QDRANT_FALLBACK_VERSION)
            download_url = f"https://github.com/qdrant/qdrant/releases/download/{tag}/{asset_name}"

        tar_path = project_root / asset_name
        print(f"  {BLUE}[...]{RESET} {download_url}")

        urllib.request.urlretrieve(download_url, tar_path)

        with tarfile.open(tar_path, "r:gz") as tar:
            for member in tar.getmembers():
                # Path traversal protection: reject members with '..' components
                if '..' in member.name or member.name.startswith('/'):
                    continue
                if member.name == "qdrant" or member.name.endswith("/qdrant"):
                    member.name = "qdrant"
                    try:
                        tar.extract(member, project_root, filter='data')
                    except TypeError:
                        tar.extract(member, project_root)
                    break

        qdrant_bin.chmod(0o755)
        tar_path.unlink()

        print_success(t('qdrant_downloaded'))
        _maybe_clear_quarantine(qdrant_bin)
        return True

    except Exception as e:
        print_warn(f"{t('qdrant_download_failed')}: {e}")
        return False


def _maybe_clear_quarantine(binary_path: Path) -> None:
    """Offer to remove Gatekeeper quarantine on macOS."""
    import platform

    if platform.system().lower() != "darwin":
        return

    info_text = t('qdrant_quarantine_info').format(bold=BOLD, reset=RESET)
    print(f"\n{BOLD}{'─'*60}{RESET}")
    print(info_text)
    print(f"{BOLD}{'─'*60}{RESET}\n")

    confirm = input(f"{t('qdrant_quarantine_prompt')} {t('yes_no')}: ").lower()
    if confirm == 'n':
        print_warn(t('qdrant_quarantine_skipped'))
        return

    result = subprocess.run(
        ["xattr", "-dr", "com.apple.quarantine", str(binary_path)],
        capture_output=True,
        text=True
    )
    if result.returncode == 0:
        print_success(t('qdrant_quarantine_cleared'))
    else:
        print_warn(t('qdrant_quarantine_failed'))
        print(f"  {CYAN}xattr -dr com.apple.quarantine {binary_path}{RESET}")
