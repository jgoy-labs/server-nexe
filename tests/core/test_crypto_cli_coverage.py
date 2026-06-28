"""Tests for core/crypto/cli.py — coverage gaps.

T87 (reforçat): prova que respondre "n" al confirm REALMENT avorta, sense el
`or exit_code==0` que emmascara l'abort trencat.
"""
from pathlib import Path
from click.testing import CliRunner


class TestCryptoCLI:
    def test_get_storage_path(self):
        from core.paths import get_storage_path
        path = get_storage_path()
        assert isinstance(path, Path)
        assert "storage" in str(path)

    def test_encryption_status_command(self):
        from core.crypto.cli import encryption
        runner = CliRunner()
        result = runner.invoke(encryption, ["status"])
        assert result.exit_code == 0
        assert "CryptoProvider" in result.output

    def test_encrypt_all_abort(self):
        """Respondre 'n' al confirm ha d'avortar SENSE arribar a carregar la clau.

        Control de seguretat: si el gate de confirmació de `encrypt-all` falla,
        l'operació procedeix sense consentiment de l'usuari.

        Prova de mutació: si click.confirm retorna True (abort trencat), el
        test es posa VERMELL perquè 'Master key loaded' apareix a la sortida.
        """
        from core.crypto.cli import encryption
        runner = CliRunner()
        result = runner.invoke(encryption, ["encrypt-all"], input="n\n")

        # L'abort ha de ser visible a la sortida
        assert "Aborted" in result.output, (
            f"Missatge 'Aborted' absent — el gate de confirmació podria no funcionar. "
            f"Sortida: {result.output!r}"
        )
        # L'operació NO ha de continuar: 'Master key loaded' és la primera
        # acció POSTERIOR al confirm (cli.py:69) i no ha d'aparèixer mai si l'abort
        # ha funcionat correctament.
        assert "Master key loaded" not in result.output, (
            f"'Master key loaded' present — l'operació va CONTINUAR malgrat respondre 'n'. "
            f"El gate de confirmació NO funciona. Sortida: {result.output!r}"
        )
