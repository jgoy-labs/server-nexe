"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/test_tray_uninstaller.py
Description: Conductual tests for perform_uninstall data-safety ordering (B149)
             and backup-failure abort (B150).

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
from installer import tray_uninstaller as tu


def _noop_t(key, **kwargs):
    return key


def test_stop_server_called_before_backup_in_perform_uninstall(tmp_path, monkeypatch):
    # B149: the server must be stopped BEFORE storage/ is copied, otherwise
    # Qdrant/SQLite may still be writing and the backup is inconsistent.
    storage = tmp_path / "storage"
    storage.mkdir()
    (storage / "user.db").write_text("data")
    install_dir = tmp_path / "install"
    install_dir.mkdir()

    order = []
    monkeypatch.setattr(tu, "_uninstall_confirm_dialogs", lambda i, t: (False, True, storage))
    monkeypatch.setattr(tu, "_uninstall_remove_system_entries", lambda r, f: None)
    monkeypatch.setattr(tu, "_uninstall_remove_install_dir", lambda i, r, f: None)
    # spy copytree WITHOUT delegating to the real one (no ~/nexe-backup-* debris)
    monkeypatch.setattr(tu.shutil, "copytree", lambda *a, **k: order.append("copytree"))

    tu.perform_uninstall(install_dir, _noop_t, lambda: order.append("stop"))

    assert order == ["stop", "copytree"]  # fail-before: ["copytree", "stop"]


def test_perform_uninstall_aborts_if_backup_fails(tmp_path, monkeypatch):
    # B150: if the user keeps data but the backup fails, NOTHING may be removed.
    storage = tmp_path / "storage"
    storage.mkdir()
    (storage / "user.db").write_text("data")
    install_dir = tmp_path / "install"
    install_dir.mkdir()

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(tu, "_uninstall_confirm_dialogs", lambda i, t: (False, True, storage))
    monkeypatch.setattr(tu.shutil, "copytree", boom)
    remove_calls = []
    monkeypatch.setattr(tu, "_uninstall_remove_system_entries", lambda r, f: remove_calls.append("sys"))
    monkeypatch.setattr(tu, "_uninstall_remove_install_dir", lambda i, r, f: remove_calls.append("dir"))

    removed, failed = tu.perform_uninstall(install_dir, _noop_t, lambda: None)

    assert remove_calls == []  # fail-before: ["sys", "dir"] (removal proceeded)
    assert removed == []
    assert "uninstall_backup_failed" in failed
    assert install_dir.exists()
