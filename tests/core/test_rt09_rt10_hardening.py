"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/core/test_rt09_rt10_hardening.py
Description: Red team 2026-06-11 hardening regressions.
    RT-09 — the master bootstrap token must NOT persist in plaintext once
    used or expired (system_core.db lives on disk unencrypted).
    RT-10 — malformed/traversal session ids must be rejected with a clean
    400 at the API boundary, never a 500.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
import sqlite3
import tempfile
from pathlib import Path


def _plaintext_master_token(db_path: Path):
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT value FROM bootstrap_config WHERE key = 'master_token'"
        ).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


class TestRT09BootstrapTokenPurge:
    def setup_method(self):
        from core.bootstrap_tokens import BootstrapTokenManager
        self.tmp = Path(tempfile.mkdtemp())
        self.manager = BootstrapTokenManager()
        self.manager._initialized = False
        self.manager.initialize_on_startup(self.tmp)
        self.db_path = self.tmp / "storage" / "system_core.db"

    def test_pending_token_still_retrievable_for_display(self):
        # Dev restarts must keep re-displaying a pending unexpired token.
        self.manager.set_bootstrap_token("tok-pending-123", ttl_minutes=30)
        info = self.manager.get_bootstrap_token()
        assert info["token"] == "tok-pending-123"
        assert info["used"] is False

    def test_used_token_purged_from_disk(self):
        self.manager.set_bootstrap_token("tok-secret-456", ttl_minutes=30)
        assert self.manager.validate_master_bootstrap("tok-secret-456") is True
        # RT-09: the plaintext secret must be gone from system_core.db.
        assert _plaintext_master_token(self.db_path) is None
        # Metadata semantics preserved: 'already used' is still reportable.
        info = self.manager.get_bootstrap_token()
        assert info is not None
        assert info["used"] is True
        assert info["token"] is None

    def test_used_token_cannot_be_replayed(self):
        self.manager.set_bootstrap_token("tok-once-789", ttl_minutes=30)
        assert self.manager.validate_master_bootstrap("tok-once-789") is True
        assert self.manager.validate_master_bootstrap("tok-once-789") is False

    def test_expired_token_purged_on_read(self):
        self.manager.set_bootstrap_token("tok-old-000", ttl_minutes=-1)
        info = self.manager.get_bootstrap_token()
        # Metadata says expired (timestamp preserved), secret is gone.
        assert info is not None
        assert info["token"] is None
        assert info["used"] is False
        assert _plaintext_master_token(self.db_path) is None

    def test_rotation_after_purge_resets_used(self):
        self.manager.set_bootstrap_token("tok-a", ttl_minutes=30)
        assert self.manager.validate_master_bootstrap("tok-a") is True
        # New token after consumption (e.g. server restart regenerates).
        self.manager.set_bootstrap_token("tok-b", ttl_minutes=30)
        info = self.manager.get_bootstrap_token()
        assert info["token"] == "tok-b"
        assert info["used"] is False
        assert self.manager.validate_master_bootstrap("tok-b") is True


class TestRT10SessionIdValidation:
    def test_traversal_ids_rejected(self):
        from plugins.web_ui_module.core.session_manager import SessionManager
        for bad in (
            "../../../../etc/passwd",
            "..",
            "a/b",
            "a\\b",
            "id with spaces",
            "id\x00null",
            "",
            None,
            123,
        ):
            assert SessionManager.is_valid_session_id(bad) is False, repr(bad)

    def test_legit_ids_accepted(self):
        from plugins.web_ui_module.core.session_manager import SessionManager
        for good in (
            "0c9b2f64-8a4e-4f1b-9d2c-1a2b3c4d5e6f",
            "sess_test-1",
            "ABC123",
        ):
            assert SessionManager.is_valid_session_id(good) is True, good
