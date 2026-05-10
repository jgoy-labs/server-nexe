"""Tests for core/crypto/cli.py — coverage gaps."""
from pathlib import Path
from click.testing import CliRunner


class TestCryptoCLI:
    def test_encryption_group_exists(self):
        from core.crypto.cli import encryption
        assert encryption is not None

    def test_get_storage_path(self):
        from core.crypto.cli import _get_storage_path
        path = _get_storage_path()
        assert isinstance(path, Path)
        assert "storage" in str(path)

    def test_encryption_status_command(self):
        from core.crypto.cli import encryption
        runner = CliRunner()
        result = runner.invoke(encryption, ["status"])
        assert result.exit_code == 0
        assert "CryptoProvider" in result.output

    def test_encrypt_all_abort(self):
        from core.crypto.cli import encryption
        runner = CliRunner()
        result = runner.invoke(encryption, ["encrypt-all"], input="n\n")
        assert "Aborted" in result.output or result.exit_code == 0
