"""
Tests for core/crypto/cli.py and core/crypto/__init__.py (encryption status check).
"""
import os
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from click.testing import CliRunner

from core.crypto.cli import encryption


class TestEncryptionStatus:
    """Test the encryption status CLI command."""

    def test_status_command_runs(self, tmp_path):
        runner = CliRunner()
        with patch("core.crypto.cli._get_storage_path", return_value=tmp_path):
            result = runner.invoke(encryption, ["status"])
        assert result.exit_code == 0

    def test_status_shows_no_db(self, tmp_path):
        runner = CliRunner()
        with patch("core.crypto.cli._get_storage_path", return_value=tmp_path):
            result = runner.invoke(encryption, ["status"])
        assert "NOT FOUND" in result.output


class TestExportKey:
    """Test the export-key CLI command."""

    def test_export_key_hex(self, tmp_path):
        key = os.urandom(32)
        runner = CliRunner()
        with patch("core.crypto.keys.get_or_create_master_key", return_value=key):
            result = runner.invoke(encryption, ["export-key", "--hex"])
        assert result.exit_code == 0
        assert key.hex() in result.output

    def test_export_key_base64(self, tmp_path):
        import base64
        key = os.urandom(32)
        runner = CliRunner()
        with patch("core.crypto.keys.get_or_create_master_key", return_value=key):
            result = runner.invoke(encryption, ["export-key"])
        assert result.exit_code == 0
        assert base64.b64encode(key).decode() in result.output


class TestCheckEncryptionStatus:
    """Test check_encryption_status() warning function."""

    def test_warns_on_plain_sqlite(self, tmp_path, caplog):
        import logging
        from core.crypto import check_encryption_status

        db_dir = tmp_path / "memory"
        db_dir.mkdir()
        (db_dir / "memories.db").write_bytes(b"SQLite format 3\x00" + b"\x00" * 100)

        with caplog.at_level(logging.WARNING, logger="core.crypto"):
            check_encryption_status(tmp_path)
        assert any("unencrypted" in r.message.lower() for r in caplog.records)

    def test_warns_on_plain_sessions(self, tmp_path, caplog):
        import logging
        from core.crypto import check_encryption_status

        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()
        (sessions_dir / "test.json").write_text("{}")

        with caplog.at_level(logging.WARNING, logger="core.crypto"):
            check_encryption_status(tmp_path)
        assert any("session" in r.message.lower() for r in caplog.records)

    def test_no_warning_when_clean(self, tmp_path, caplog):
        import logging
        from core.crypto import check_encryption_status

        with caplog.at_level(logging.WARNING, logger="core.crypto"):
            check_encryption_status(tmp_path)
        assert not any(r.levelno >= logging.WARNING for r in caplog.records)

    def test_no_warning_encrypted_db(self, tmp_path, caplog):
        import logging
        from core.crypto import check_encryption_status

        db_dir = tmp_path / "memory"
        db_dir.mkdir()
        (db_dir / "memories.db").write_bytes(os.urandom(100))

        with caplog.at_level(logging.WARNING, logger="core.crypto"):
            check_encryption_status(tmp_path)
        assert not any(r.levelno >= logging.WARNING for r in caplog.records)
