# -*- coding: utf-8 -*-
"""Propagate the project version (pyproject.toml) to Info.plist files that
cannot import Python at runtime (.app bundles on macOS).

Complementary to ``core/version.py``:
- ``core/version.py`` reads pyproject.toml at runtime (Python code).
- This script writes to Info.plist files at build time (macOS bundles).

Synced bundles (share the server-nexe version):
- ``Nexe.app/Contents/Info.plist``
- ``installer/NexeTray.app/Contents/Info.plist``

NOT synced bundles (have their own installer version):
- ``Install Nexe.app`` / ``InstallNexe.app`` / ``swift-wizard/Resources``

Usage:
    python -m installer.sync_plist_versions            # apply changes
    python -m installer.sync_plist_versions --check    # verify only (CI)
"""

from __future__ import annotations

import plistlib
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python < 3.11
    import tomli as tomllib  # type: ignore[no-redef]

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = PROJECT_ROOT / "pyproject.toml"

# Bundles that must share the server-nexe version.
# Add new ones here when needed.
SYNCED_PLISTS: tuple[Path, ...] = (
    PROJECT_ROOT / "Nexe.app" / "Contents" / "Info.plist",
    PROJECT_ROOT / "installer" / "NexeTray.app" / "Contents" / "Info.plist",
)


def _project_version() -> str:
    with open(PYPROJECT, "rb") as f:
        return tomllib.load(f)["project"]["version"]


def _read_plist(path: Path) -> dict:
    with open(path, "rb") as f:
        return plistlib.load(f)


def _write_plist(path: Path, data: dict) -> None:
    with open(path, "wb") as f:
        plistlib.dump(data, f)


def sync(check_only: bool = False) -> int:
    """Sync (or verify) versions. Return number of files out of sync."""
    version = _project_version()
    out_of_sync = 0

    for plist_path in SYNCED_PLISTS:
        if not plist_path.exists():
            print(f"[SKIP] {plist_path} does not exist", file=sys.stderr)
            continue

        data = _read_plist(plist_path)
        current_short = data.get("CFBundleShortVersionString")
        current_build = data.get("CFBundleVersion")

        if current_short == version and current_build == version:
            continue

        out_of_sync += 1
        if check_only:
            print(
                f"[OUT OF SYNC] {plist_path.relative_to(PROJECT_ROOT)}: "
                f"short={current_short!r}, build={current_build!r} → expected {version!r}"
            )
        else:
            data["CFBundleShortVersionString"] = version
            data["CFBundleVersion"] = version
            _write_plist(plist_path, data)
            print(f"[SYNCED] {plist_path.relative_to(PROJECT_ROOT)} → {version}")

    return out_of_sync


if __name__ == "__main__":
    check = "--check" in sys.argv[1:]
    diff = sync(check_only=check)
    if check and diff:
        print(f"\n{diff} plist(s) out of sync. Run: python -m installer.sync_plist_versions")
        sys.exit(1)
    sys.exit(0)
