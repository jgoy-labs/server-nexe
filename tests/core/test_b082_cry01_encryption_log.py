"""
────────────────────────────────────
Server Nexe — test
Author: Jordi Goy
Location: tests/core/test_b082_cry01_encryption_log.py
Description: B082 (CRY-01) — el missatge "Encryption at rest: ENABLED" s'ha
d'emetre quan l'encriptació està activa, i NO quan no hi ha SQLCipher.

Aquest test fixa el CONTRACTE del qual depèn el gate del build
(nexe-app/scripts/build-sidecar.sh fa `grep "Encryption at rest: ENABLED"`
sobre el boot log per validar CRY-01). Si algú canvia el text del log, aquest
test peta i avisa que el gate del build quedaria silenciosament trencat.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import logging
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from core.lifespan_crypto import _apply_crypto_provider

ENABLED_MSG = "Encryption at rest: ENABLED"


def test_crypto_enabled_logs_encryption_at_rest(caplog):
    """With encryption active: the provider is set and the ENABLED message is logged."""
    server_state = SimpleNamespace(crypto_provider=None)
    # CryptoProvider is a LOCAL import inside _apply_crypto_provider → patch at the source module.
    with patch("core.crypto.CryptoProvider", return_value=MagicMock()) as mock_cp:
        with caplog.at_level(logging.INFO, logger="core.lifespan_crypto"):
            _apply_crypto_provider(
                server_state,
                crypto_enabled=True,
                normalized_env="true",
                sqlcipher_available=True,
            )

    assert ENABLED_MSG in caplog.text
    assert server_state.crypto_provider is mock_cp.return_value


def test_no_sqlcipher_does_not_log_enabled(caplog):
    """Without SQLCipher (auto): plaintext banner, NEVER the ENABLED message."""
    server_state = SimpleNamespace(crypto_provider=None)
    # format_plaintext_startup_banner is also a LOCAL import → patch at the source module.
    with patch(
        "core.crypto.format_plaintext_startup_banner",
        return_value="PLAINTEXT-WARNING-BANNER",
    ) as mock_banner:
        with caplog.at_level(logging.WARNING, logger="core.lifespan_crypto"):
            _apply_crypto_provider(
                server_state,
                crypto_enabled=False,
                normalized_env="",
                sqlcipher_available=False,
            )

    assert ENABLED_MSG not in caplog.text
    assert "PLAINTEXT-WARNING-BANNER" in caplog.text
    mock_banner.assert_called_once()
