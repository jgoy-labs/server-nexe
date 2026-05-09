"""
Tests for installer/installer_reinstall.py — Bug 7 fix release v0.9.0.

Covers the 3 reinstall modes:
- wipe       → deletes all user data
- overwrite  → preserves data, only clears venv
- backup     → performs backup first then wipe

Also verifies detect_existing_install() and mode validation.
"""

from pathlib import Path

import pytest

from installer.installer_reinstall import (
    DEFAULT_REINSTALL_MODE,
    REINSTALL_MODE_BACKUP,
    REINSTALL_MODE_OVERWRITE,
    REINSTALL_MODE_WIPE,
    VALID_REINSTALL_MODES,
    apply_reinstall_mode,
    backup_user_data,
    detect_existing_install,
    wipe_user_data,
)
from installer import installer_reinstall as ir


def _make_install(root: Path) -> None:
    """Creates a fake installation with .env, storage/, knowledge/, venv/."""
    (root / ".env").write_text("NEXE_PRIMARY_API_KEY=secret-key\n")
    (root / "storage").mkdir()
    (root / "storage" / "vectors").mkdir()
    (root / "storage" / "vectors" / "qdrant.db").write_text("vectors")
    (root / "knowledge").mkdir(exist_ok=True)
    (root / "knowledge" / "doc.md").write_text("# doc")
    (root / "venv").mkdir()
    (root / "venv" / "bin").mkdir()
    (root / "venv" / "bin" / "python").write_text("#!/bin/sh")


# ── detect_existing_install ────────────────────────────────────────────


def test_detect_existing_install_empty_dir(tmp_path):
    assert detect_existing_install(tmp_path) is False


def test_detect_existing_install_with_env(tmp_path):
    (tmp_path / ".env").write_text("x")
    assert detect_existing_install(tmp_path) is True


def test_detect_existing_install_with_storage(tmp_path):
    (tmp_path / "storage").mkdir()
    assert detect_existing_install(tmp_path) is True


def test_detect_existing_install_with_venv(tmp_path):
    (tmp_path / "venv").mkdir()
    assert detect_existing_install(tmp_path) is True


# ── wipe_user_data ──────────────────────────────────────────────────────


def test_wipe_user_data_removes_env_and_storage(tmp_path):
    """knowledge/ is system documentation (ingested, not user data).
    wipe_user_data removes .env and storage/, but preserves knowledge/ because
    the payload tar overwrites it during reinstall."""
    _make_install(tmp_path)
    removed = wipe_user_data(tmp_path)
    removed_names = {p.name for p in removed}
    assert ".env" in removed_names
    assert "storage" in removed_names
    assert "knowledge" not in removed_names
    assert not (tmp_path / ".env").exists()
    assert not (tmp_path / "storage").exists()
    assert (tmp_path / "knowledge").exists()
    # venv is NOT touched by wipe_user_data — that is done by apply_reinstall_mode
    assert (tmp_path / "venv").exists()


def test_wipe_user_data_idempotent(tmp_path):
    # With nothing present, does not raise
    removed = wipe_user_data(tmp_path)
    assert removed == []


# ── backup_user_data ────────────────────────────────────────────────────


def test_backup_user_data_creates_timestamped_dir(tmp_path):
    _make_install(tmp_path)
    backup_dir = backup_user_data(tmp_path)
    assert backup_dir.exists()
    assert backup_dir.is_dir()
    # .nexe-backups/<timestamp>/  (outside storage/ to survive the wipe)
    assert backup_dir.parent == tmp_path / ".nexe-backups"


def test_backup_user_data_moves_files(tmp_path):
    """Advisory 4 Consultant — backup uses `shutil.move`, not `copytree`.

    This means that after backup the originals are NO LONGER present in
    project_root (they have been moved, not copied). It is instantaneous on
    the same volume and does not require 2x disk space.
    """
    _make_install(tmp_path)
    backup_dir = backup_user_data(tmp_path)
    assert (backup_dir / ".env").exists()
    assert (backup_dir / ".env").read_text() == "NEXE_PRIMARY_API_KEY=secret-key\n"
    # knowledge/ does NOT go to the backup — it is system documentation, the tar overwrites it
    assert not (backup_dir / "knowledge").exists()
    # .env has been moved (not copied)
    assert not (tmp_path / ".env").exists()
    # knowledge/ is preserved in-place (not user data)
    assert (tmp_path / "knowledge" / "doc.md").exists()


def test_backup_does_not_recurse_into_existing_backups(tmp_path):
    """Dev #3 fix (Consultant pass 1, finding 4): the original test
    checked `backup2/storage/backups` but the real code uses
    `.nexe-backups/` as the backup folder, so the assert was passing
    by construction without testing anything. We now verify that the second
    backup does NOT recursively contain the `.nexe-backups` directory within it
    (otherwise it would be a backup containing the previous backup and would grow
    exponentially)."""
    _make_install(tmp_path)
    # First pass: creates .nexe-backups/<ts1>/
    backup1 = backup_user_data(tmp_path)
    assert backup1.parent == tmp_path / ".nexe-backups"
    # Rebuild data to allow a second pass
    # (venv is not touched by backup, so we remove it first)
    if (tmp_path / "venv").exists():
        shutil.rmtree(tmp_path / "venv")
    _make_install(tmp_path)
    # Second pass: must not recurse into .nexe-backups/
    backup2 = backup_user_data(tmp_path)
    assert backup2.parent == tmp_path / ".nexe-backups"
    # The second backup must NOT contain `.nexe-backups` within it
    # (neither directly nor inside storage/)
    nested_backups_root = backup2 / ".nexe-backups"
    assert not nested_backups_root.exists(), (
        "backup recursed into itself at backup_dir root"
    )
    nested_storage_backups = backup2 / "storage" / ".nexe-backups"
    assert not nested_storage_backups.exists(), (
        "backup recursed into itself via storage/.nexe-backups"
    )
    # The first backup is still accessible (has not been moved into the second)
    assert backup1.exists()
    assert (backup1 / ".env").exists()


# ── apply_reinstall_mode: WIPE ──────────────────────────────────────────


def test_apply_wipe_removes_user_data_and_venv(tmp_path):
    """WIPE removes .env, storage/ and venv, but preserves knowledge/
    (system documentation — the tar overwrites it during reinstall)."""
    _make_install(tmp_path)
    summary = apply_reinstall_mode(tmp_path, REINSTALL_MODE_WIPE)
    assert summary["mode"] == REINSTALL_MODE_WIPE
    assert summary["backup_dir"] is None
    assert not (tmp_path / ".env").exists()
    assert not (tmp_path / "storage").exists()
    assert (tmp_path / "knowledge").exists()
    assert not (tmp_path / "venv").exists()


# ── apply_reinstall_mode: OVERWRITE ─────────────────────────────────────


def test_apply_overwrite_preserves_user_data(tmp_path):
    _make_install(tmp_path)
    summary = apply_reinstall_mode(tmp_path, REINSTALL_MODE_OVERWRITE)
    assert summary["mode"] == REINSTALL_MODE_OVERWRITE
    assert summary["backup_dir"] is None
    # Data preserved
    assert (tmp_path / ".env").exists()
    assert (tmp_path / "storage" / "vectors" / "qdrant.db").exists()
    assert (tmp_path / "knowledge" / "doc.md").exists()
    # Venv removed (will be regenerated)
    assert not (tmp_path / "venv").exists()


def test_apply_overwrite_no_venv_no_op(tmp_path):
    (tmp_path / ".env").write_text("x")
    summary = apply_reinstall_mode(tmp_path, REINSTALL_MODE_OVERWRITE)
    assert summary["removed"] == []


# ── apply_reinstall_mode: BACKUP ────────────────────────────────────────


def test_apply_backup_then_wipe(tmp_path):
    _make_install(tmp_path)
    summary = apply_reinstall_mode(tmp_path, REINSTALL_MODE_BACKUP)
    assert summary["mode"] == REINSTALL_MODE_BACKUP
    assert summary["backup_dir"] is not None

    backup_dir = Path(summary["backup_dir"])
    assert backup_dir.exists()
    # Backup contains user data
    assert (backup_dir / ".env").read_text() == "NEXE_PRIMARY_API_KEY=secret-key\n"
    # knowledge/ does NOT go to the backup — it is system documentation
    assert not (backup_dir / "knowledge").exists()

    # .env and venv have been removed
    assert not (tmp_path / ".env").exists()
    assert not (tmp_path / "venv").exists()
    # knowledge/ is preserved in-place (the tar will overwrite it)
    assert (tmp_path / "knowledge" / "doc.md").exists()
    # storage/ has been deleted (backup already made a copy)
    # But since the backup created storage/backups/<timestamp>, after
    # the wipe the entire 'storage' directory is gone. The backup_dir
    # may reside outside if it was created inside storage/. We verify that
    # at least the backup contents exist.
    assert backup_dir.exists()


def test_apply_backup_with_custom_backup_root(tmp_path):
    _make_install(tmp_path)
    custom_backup = tmp_path.parent / "external_backups"
    summary = apply_reinstall_mode(
        tmp_path, REINSTALL_MODE_BACKUP, backup_root=custom_backup
    )
    assert Path(summary["backup_dir"]).parent == custom_backup
    # The external backup survives the project_root wipe
    assert Path(summary["backup_dir"]).exists()
    assert (Path(summary["backup_dir"]) / ".env").exists()


# ── Validation ──────────────────────────────────────────────────────────


def test_apply_invalid_mode_raises(tmp_path):
    _make_install(tmp_path)
    with pytest.raises(ValueError, match="Invalid reinstall mode"):
        apply_reinstall_mode(tmp_path, "invalid_mode")


def test_default_mode_is_backup():
    assert DEFAULT_REINSTALL_MODE == REINSTALL_MODE_BACKUP


def test_all_modes_in_valid_set():
    assert REINSTALL_MODE_WIPE in VALID_REINSTALL_MODES
    assert REINSTALL_MODE_OVERWRITE in VALID_REINSTALL_MODES
    assert REINSTALL_MODE_BACKUP in VALID_REINSTALL_MODES
    assert len(VALID_REINSTALL_MODES) == 3


# ════════════════════════════════════════════════════════════════════════
# Tests Dev #2 — application of the 7 Consultant advisories
# ════════════════════════════════════════════════════════════════════════


# ── Advisory 1: stop server before any mode ─────────────────────────────


def test_stop_server_called_before_any_mode(tmp_path):
    """stop_server_func must be called before touching anything."""
    _make_install(tmp_path)
    calls = []

    def fake_stop(root):
        calls.append(root)
        # When called, .env is still there (has not been touched)
        assert (root / ".env").exists()
        return True

    for mode in (REINSTALL_MODE_WIPE, REINSTALL_MODE_OVERWRITE, REINSTALL_MODE_BACKUP):
        _make_install(tmp_path) if not (tmp_path / ".env").exists() else None
        if not (tmp_path / ".env").exists():
            (tmp_path / ".env").write_text("x")
            (tmp_path / "storage").mkdir(exist_ok=True)
            (tmp_path / "knowledge").mkdir(exist_ok=True)
        calls.clear()
        apply_reinstall_mode(tmp_path, mode, stop_server_func=fake_stop)
        assert len(calls) == 1, f"stop_server_func not called for mode={mode}"


def test_apply_aborts_if_stop_server_fails(tmp_path):
    _make_install(tmp_path)

    def failing_stop(root):
        return False  # server alive, cannot be stopped

    with pytest.raises(RuntimeError, match="Could not stop"):
        apply_reinstall_mode(
            tmp_path, REINSTALL_MODE_WIPE, stop_server_func=failing_stop
        )
    # Data intact
    assert (tmp_path / ".env").exists()
    assert (tmp_path / "storage").exists()


def test_default_stop_server_no_pidfile(tmp_path):
    """Without a pidfile, _default_stop_server returns True without error."""
    assert ir._default_stop_server(tmp_path) is True


def test_default_stop_server_stale_pidfile(tmp_path):
    """Pidfile with a dead PID → returns True and removes the pidfile."""
    pid_dir = tmp_path / "storage" / "logs"
    pid_dir.mkdir(parents=True)
    pid_file = pid_dir / "core_supervisor.pid"
    # PID most likely dead (high and arbitrary)
    pid_file.write_text("999999")
    assert ir._default_stop_server(tmp_path) is True
    assert not pid_file.exists()


# ── Advisory 2: overwrite regenerates .env preserving secrets ────────────


def test_mode_overwrite_regenerates_env_keeping_secrets(tmp_path):
    """Overwrite mode must preserve the API key and CSRF via _update_env_model_config.

    apply_reinstall_mode does not rewrite the .env itself —
    it only validates that it is readable. The actual regeneration happens when
    generate_env_file() is called later in the installer flow. Here we verify
    the contract: (a) the .env remains intact after overwrite and (b)
    _update_env_model_config preserves secrets when the installer calls it afterwards.
    """
    _make_install(tmp_path)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "NEXE_PRIMARY_API_KEY=supersecret-abc123\n"
        "NEXE_CSRF_SECRET=csrf-xyz789\n"
        "NEXE_DEFAULT_MODEL=gemma3_4b\n"
        "NEXE_MODEL_ENGINE=ollama\n"
        "NEXE_OLLAMA_MODEL=gemma3:4b\n"
    )
    apply_reinstall_mode(tmp_path, REINSTALL_MODE_OVERWRITE)
    # .env is still there (overwrite does not delete it)
    assert env_file.exists()
    content = env_file.read_text()
    assert "NEXE_PRIMARY_API_KEY=supersecret-abc123" in content
    assert "NEXE_CSRF_SECRET=csrf-xyz789" in content

    # Now simulate the installer calling the merge with a new model
    from installer.installer_setup_config import _update_env_model_config
    new_model = {
        "id": "qwen2.5:7b",
        "engine": "ollama",
        "prompt_tier": "full",
    }
    _update_env_model_config(env_file, new_model)
    after = env_file.read_text()
    # Secrets preserved
    assert "NEXE_PRIMARY_API_KEY=supersecret-abc123" in after
    assert "NEXE_CSRF_SECRET=csrf-xyz789" in after
    # Model refreshed
    assert "NEXE_DEFAULT_MODEL=qwen2.5:7b" in after
    assert "NEXE_OLLAMA_MODEL=qwen2.5:7b" in after


# ── Advisory 3: overwrite clears the .knowledge_ingested marker ──────────


def test_mode_overwrite_clears_knowledge_ingested_marker(tmp_path):
    _make_install(tmp_path)
    marker = tmp_path / "storage" / ".knowledge_ingested"
    marker.touch()
    assert marker.exists()

    summary = apply_reinstall_mode(tmp_path, REINSTALL_MODE_OVERWRITE)
    assert not marker.exists()
    assert str(marker) in summary["removed"]
    # Storage and knowledge preserved for the rest
    assert (tmp_path / "storage" / "vectors" / "qdrant.db").exists()
    assert (tmp_path / "knowledge" / "doc.md").exists()


# ── Advisory 4: backup uses move, not copytree ───────────────────────────


def test_mode_backup_uses_move_not_copytree(monkeypatch, tmp_path):
    """Verifies that backup calls shutil.move and not shutil.copytree."""
    _make_install(tmp_path)

    move_calls = []
    copytree_calls = []

    real_move = shutil.move
    real_copytree = shutil.copytree

    def tracking_move(src, dst, *a, **kw):
        move_calls.append((str(src), str(dst)))
        return real_move(src, dst, *a, **kw)

    def tracking_copytree(src, dst, *a, **kw):
        copytree_calls.append((str(src), str(dst)))
        return real_copytree(src, dst, *a, **kw)

    monkeypatch.setattr(ir.shutil, "move", tracking_move)
    monkeypatch.setattr(ir.shutil, "copytree", tracking_copytree)

    backup_user_data(tmp_path)

    assert len(move_calls) > 0, "backup must use shutil.move"
    assert len(copytree_calls) == 0, "backup must NOT use shutil.copytree"


def test_mode_backup_excludes_models_by_default(tmp_path):
    """By default, storage/models/ (can be 30+ GB) remains in place."""
    _make_install(tmp_path)
    models_dir = tmp_path / "storage" / "models"
    models_dir.mkdir(parents=True)
    big_file = models_dir / "gemma3-12b.gguf"
    big_file.write_text("fake-huge-model")

    backup_dir = backup_user_data(tmp_path, exclude_models=True)

    # Models are NOT in the backup
    assert not (backup_dir / "storage" / "models").exists()
    # Models are still at their original location
    assert big_file.exists()
    # But other storage subdirs have been moved to the backup
    assert (backup_dir / "storage" / "vectors" / "qdrant.db").exists()


def test_mode_backup_includes_models_when_optin(tmp_path):
    _make_install(tmp_path)
    models_dir = tmp_path / "storage" / "models"
    models_dir.mkdir(parents=True)
    (models_dir / "m.gguf").write_text("x")

    backup_dir = backup_user_data(tmp_path, exclude_models=False)
    # With opt-in, entire storage/ is moved (including models/)
    assert (backup_dir / "storage" / "models" / "m.gguf").exists()


# ── Advisory 5: refuse wipe if project_root is the running bundle ─────────


def test_refuses_wipe_if_install_path_inside_running_bundle(tmp_path, monkeypatch):
    _make_install(tmp_path)

    def fake_is_bundle(root):
        return True

    monkeypatch.setattr(ir, "_is_project_root_running_bundle", fake_is_bundle)

    for mode in (REINSTALL_MODE_WIPE, REINSTALL_MODE_BACKUP):
        with pytest.raises(RuntimeError, match="Refusing to wipe"):
            apply_reinstall_mode(tmp_path, mode)
    # Data intact
    assert (tmp_path / ".env").exists()


def test_overwrite_allowed_even_if_inside_bundle(tmp_path, monkeypatch):
    """Overwrite does NOT perform a global wipe, so it is allowed even if project_root
    is inside the bundle (only touches venv + marker)."""
    _make_install(tmp_path)
    monkeypatch.setattr(ir, "_is_project_root_running_bundle", lambda r: True)

    # Must not raise
    apply_reinstall_mode(tmp_path, REINSTALL_MODE_OVERWRITE)
    assert (tmp_path / ".env").exists()


# ── Advisory 6: master key in Keychain — not touched by default ──────────


def test_wipe_does_not_touch_keychain_by_default(tmp_path, monkeypatch):
    _make_install(tmp_path)

    called = {"delete": False}

    def fake_delete():
        called["delete"] = True
        return True

    monkeypatch.setattr(ir, "_wipe_keychain_master_key", fake_delete)

    apply_reinstall_mode(tmp_path, REINSTALL_MODE_WIPE)
    assert called["delete"] is False


def test_wipe_keychain_optin(tmp_path, monkeypatch):
    _make_install(tmp_path)

    called = {"delete": False}

    def fake_delete():
        called["delete"] = True
        return True

    monkeypatch.setattr(ir, "_wipe_keychain_master_key", fake_delete)

    apply_reinstall_mode(tmp_path, REINSTALL_MODE_WIPE, wipe_keychain=True)
    assert called["delete"] is True


# ── Advisory 7: ~/.nexe/mail365*.json — not touched by default ───────────


def test_wipe_does_not_touch_home_nexe_by_default(tmp_path, monkeypatch):
    _make_install(tmp_path)

    called = {"oauth": False}

    def fake_oauth():
        called["oauth"] = True
        return []

    monkeypatch.setattr(ir, "_wipe_home_nexe_oauth", fake_oauth)

    apply_reinstall_mode(tmp_path, REINSTALL_MODE_WIPE)
    assert called["oauth"] is False


def test_wipe_home_nexe_optin(tmp_path, monkeypatch):
    _make_install(tmp_path)

    called = {"oauth": False}

    def fake_oauth():
        called["oauth"] = True
        return [Path("/tmp/fake-mail365.json")]  # nosemgrep

    monkeypatch.setattr(ir, "_wipe_home_nexe_oauth", fake_oauth)

    apply_reinstall_mode(tmp_path, REINSTALL_MODE_WIPE, wipe_home_nexe=True)
    assert called["oauth"] is True


import shutil  # noqa: E402 — usat pels tests de move tracking


# ════════════════════════════════════════════════════════════════════════
# Tests Dev #3 — Consultant pass 1 fixes
# ════════════════════════════════════════════════════════════════════════


# ── Finding 2: BACKUP mode must preserve storage/models/ end-to-end ─────


def test_apply_backup_preserves_models_end_to_end(tmp_path):
    """Finding 2 Consultant pass 1: before the fix, BACKUP mode called
    backup_user_data(exclude_models=True) — which preserved models/ — and
    then called wipe_user_data with USER_DATA_PATHS including 'storage'
    → shutil.rmtree(storage) deleted the models we had preserved.
    The post-backup wipe is now selective and skips storage/models/."""
    _make_install(tmp_path)
    models_dir = tmp_path / "storage" / "models"
    models_dir.mkdir(parents=True)
    model_file = models_dir / "gemma3-12b.gguf"
    model_file.write_text("fake-huge-model")
    # More typical subdir inside storage/ that SHOULD be cleaned
    sessions_dir = tmp_path / "storage" / "sessions"
    sessions_dir.mkdir()
    (sessions_dir / "s1.json").write_text("{}")

    summary = apply_reinstall_mode(
        tmp_path, REINSTALL_MODE_BACKUP, exclude_models=True
    )
    assert summary["mode"] == REINSTALL_MODE_BACKUP
    backup_dir = Path(summary["backup_dir"])
    assert backup_dir.exists()

    # Assert 1: models preserved in-place, at their original location
    assert model_file.exists(), (
        "BACKUP mode was destroying preserved models — Bug 7 Consultant"
    )
    assert model_file.read_text() == "fake-huge-model"

    # Assert 2: backup contains the "normal" storage/ data
    assert (backup_dir / "storage" / "sessions" / "s1.json").exists()

    # Assert 3: original storage/sessions/ is no longer there (moved to backup)
    assert not sessions_dir.exists()

    # Assert 4: .env in backup; knowledge/ NOT (is system, preserved in-place)
    assert (backup_dir / ".env").exists()
    assert not (backup_dir / "knowledge").exists()
    assert (tmp_path / "knowledge").exists()

    # Assert 5: venv removed for reinstall
    assert not (tmp_path / "venv").exists()


def test_apply_backup_full_wipe_when_include_models(tmp_path):
    """Confirms that the behavior with exclude_models=False is complete
    (full wipe of storage/) — no regression from the old path."""
    _make_install(tmp_path)
    (tmp_path / "storage" / "models").mkdir(parents=True)
    (tmp_path / "storage" / "models" / "m.gguf").write_text("x")

    apply_reinstall_mode(
        tmp_path, REINSTALL_MODE_BACKUP, exclude_models=False
    )
    # With opt-in, entire storage/ is in the backup (and originals are gone)
    assert not (tmp_path / "storage").exists()


# ── Finding 5: e2e overwrite preserves secrets via generate_env_file ─────


def test_apply_overwrite_preserves_secrets_e2e(tmp_path):
    """Finding 5 Consultant pass 1: full flow
    apply_reinstall_mode(OVERWRITE) → generate_env_file() real → secrets
    preserved. Previously we only verified the _update_env_model_config unit
    but not the full flow."""
    _make_install(tmp_path)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "NEXE_PRIMARY_API_KEY=abc123\n"
        "NEXE_CSRF_SECRET=xyz789\n"
        "NEXE_ENV=production\n"
        "NEXE_DEFAULT_MODEL=gemma3_4b\n"
        "NEXE_MODEL_ENGINE=ollama\n"
        "NEXE_OLLAMA_MODEL=gemma3:4b\n"
        "NEXE_PROMPT_TIER=full\n"
    )

    # Step 1 — apply overwrite: .env must remain intact
    apply_reinstall_mode(tmp_path, REINSTALL_MODE_OVERWRITE)
    assert env_file.exists()

    # Step 2 — full flow: installer calls generate_env_file with a
    # model config (possibly different from before). Since .env exists,
    # generate_env_file delegates to _update_env_model_config which must
    # preserve the secrets.
    from installer.installer_setup_config import generate_env_file
    new_model = {
        "id": "qwen2.5:7b",
        "engine": "ollama",
        "prompt_tier": "full",
    }
    # generate_env_file prints to stdout — OK, we only care about
    # the contents of the final file.
    generate_env_file(tmp_path, new_model)

    content = env_file.read_text()
    # Assert secrets intact
    assert "NEXE_PRIMARY_API_KEY=abc123" in content, (
        "API key lost after generate_env_file (critical bug)"
    )
    assert "NEXE_CSRF_SECRET=xyz789" in content, (
        "CSRF secret lost after generate_env_file (critical bug)"
    )
    # Assert model refreshed
    assert "NEXE_DEFAULT_MODEL=qwen2.5:7b" in content
    assert "NEXE_OLLAMA_MODEL=qwen2.5:7b" in content
