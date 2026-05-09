# -*- coding: utf-8 -*-
"""Tests for installer.sync_plist_versions — the Info.plist bundles
must match pyproject.toml (server-nexe version)."""

from installer.sync_plist_versions import SYNCED_PLISTS, _project_version, sync


def test_synced_plists_match_pyproject():
    """All Info.plist entries in SYNCED_PLISTS must match the project version."""
    out_of_sync = sync(check_only=True)
    assert out_of_sync == 0, (
        f"{out_of_sync} Info.plist fora de sync amb pyproject.toml. "
        f"Executa: python -m installer.sync_plist_versions"
    )


def test_synced_plists_list_not_empty():
    """Sanity check: the list of bundles to sync is not empty."""
    assert len(SYNCED_PLISTS) > 0


def test_project_version_readable():
    """_project_version() must return a non-empty version."""
    version = _project_version()
    assert version
    assert version != "0.0.0-unknown"
