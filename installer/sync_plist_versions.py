# -*- coding: utf-8 -*-
"""Propaga la versió del projecte (pyproject.toml) cap als Info.plist que
no poden importar Python en runtime (.app bundles macOS).

Complementari a ``core/version.py``:
- ``core/version.py`` llegeix pyproject.toml en runtime (codi Python).
- Aquest script escriu als Info.plist en build-time (bundles macOS).

Bundles sincronitzats (comparteixen versió de server-nexe):
- ``Nexe.app/Contents/Info.plist``
- ``installer/NexeTray.app/Contents/Info.plist``

Bundles NO sincronitzats (tenen la seva pròpia versió d'installer):
- ``Install Nexe.app`` / ``InstallNexe.app`` / ``swift-wizard/Resources``

Ús:
    python -m installer.sync_plist_versions            # aplica canvis
    python -m installer.sync_plist_versions --check    # només verifica (CI)
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

# Bundles que han de compartir la versió de server-nexe.
# Afegir-ne de nous aquí quan calgui.
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
    """Sincronitza (o verifica) versions. Retorna nombre de fitxers fora de sync."""
    version = _project_version()
    out_of_sync = 0

    for plist_path in SYNCED_PLISTS:
        if not plist_path.exists():
            print(f"[SKIP] {plist_path} no existeix", file=sys.stderr)
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
                f"short={current_short!r}, build={current_build!r} → esperat {version!r}"
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
        print(f"\n{diff} plist(s) fora de sync. Executa: python -m installer.sync_plist_versions")
        sys.exit(1)
    sys.exit(0)
