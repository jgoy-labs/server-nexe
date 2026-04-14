# -*- coding: utf-8 -*-
"""Tests per installer.sync_plist_versions — els Info.plist dels bundles
han de coincidir amb pyproject.toml (versió de server-nexe)."""

from installer.sync_plist_versions import SYNCED_PLISTS, _project_version, sync


def test_synced_plists_match_pyproject():
    """Tots els Info.plist de SYNCED_PLISTS han de tenir la versió del projecte."""
    out_of_sync = sync(check_only=True)
    assert out_of_sync == 0, (
        f"{out_of_sync} Info.plist fora de sync amb pyproject.toml. "
        f"Executa: python -m installer.sync_plist_versions"
    )


def test_synced_plists_list_not_empty():
    """Sanity check: la llista de bundles a sincronitzar no està buida."""
    assert len(SYNCED_PLISTS) > 0


def test_project_version_readable():
    """_project_version() ha de retornar una versió no buida."""
    version = _project_version()
    assert version
    assert version != "0.0.0-unknown"
