"""
────────────────────────────────────
Server Nexe
Location: installer/installer_setup_qdrant.py
Description: Qdrant binary download and macOS quarantine management.
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

    confirm = input(f"{t('qdrant_download_prompt')} {t('yes_no')}: ").lower()
    if confirm == 'n':
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
        import urllib.request
        import json

        api_url = "https://api.github.com/repos/qdrant/qdrant/releases/latest"
        with urllib.request.urlopen(api_url, timeout=10) as response:
            release_data = json.loads(response.read().decode())

        download_url = None
        for asset in release_data.get("assets", []):
            if asset["name"] == asset_name:
                download_url = asset["browser_download_url"]
                break

        if not download_url:
            print_warn(f"Asset {asset_name} not found in release")
            return False

        tar_path = project_root / asset_name
        print(f"  {BLUE}[...]{RESET} {download_url}")

        urllib.request.urlretrieve(download_url, tar_path)

        with tarfile.open(tar_path, "r:gz") as tar:
            for member in tar.getmembers():
                if member.name == "qdrant" or member.name.endswith("/qdrant"):
                    member.name = "qdrant"
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
