"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/lifespan_crypto.py
Description: Encryption-at-rest startup helper extracted from lifespan.py.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import logging
import os

logger = logging.getLogger(__name__)


def _check_sqlcipher_required(normalized_env: str, sqlcipher_available: bool) -> None:
    """Raise RuntimeError if encryption is explicitly required but sqlcipher3 is missing."""
    if normalized_env == 'true' and not sqlcipher_available:
        raise RuntimeError(
            "Encryption at rest requested (NEXE_ENCRYPTION_ENABLED=true) "
            "but sqlcipher3 is not installed. The server will NOT start to avoid "
            "a false sense of security. Either:\n"
            "  (1) Install sqlcipher3: pip install sqlcipher3-binary\n"
            "  (2) Disable encryption: NEXE_ENCRYPTION_ENABLED=false"
        )


def _check_plaintext_db_exists(server_state, crypto_enabled: bool, normalized_env: str) -> bool:
    """P1-D: In auto mode, disable encryption if an existing plain-text DB is detected.

    Returns the (possibly updated) crypto_enabled flag.
    """
    if not (crypto_enabled and normalized_env in ('', 'auto')):
        return crypto_enabled

    storage_path_check = server_state.project_root / "storage" if server_state.project_root else None
    if not storage_path_check:
        return crypto_enabled

    db_path = storage_path_check / "memory" / "memories.db"
    if not db_path.exists():
        return crypto_enabled

    try:
        with open(db_path, 'rb') as _f:
            _header = _f.read(16)
        if _header == b'SQLite format 3\x00':
            logger.warning(
                "Encryption auto=ON skipped: existing plain-text memories.db detected. "
                "Run 'nexe encryption encrypt-all' to migrate data, then restart. "
                "Set NEXE_ENCRYPTION_ENABLED=false to suppress this warning."
            )
            return False
    except Exception:  # nosec B110
        pass

    return crypto_enabled


def _apply_crypto_provider(server_state, crypto_enabled: bool, normalized_env: str, sqlcipher_available: bool) -> None:
    """Set server_state.crypto_provider and log the outcome."""
    if crypto_enabled:
        from core.crypto import CryptoProvider
        server_state.crypto_provider = CryptoProvider()
        logger.info("Encryption at rest: ENABLED (AES-256-GCM)")
    elif normalized_env in ('', 'auto') and not sqlcipher_available:
        from core.crypto import format_plaintext_startup_banner
        logger.warning(format_plaintext_startup_banner())
    else:
        logger.info("Encryption at rest: disabled")


async def _startup_encryption(server_state) -> None:
    """Initialize encryption-at-rest (opt-in). Modifies server_state.crypto_provider."""
    from core.lifespan import _resolve_encryption_enabled  # avoid circular at module level

    try:
        from core.crypto import check_encryption_status
        from memory.memory.engines.persistence import SQLCIPHER_AVAILABLE

        encryption_config = server_state.config.get('security', {}).get('encryption', {})
        env_crypto = os.environ.get('NEXE_ENCRYPTION_ENABLED', 'auto')
        normalized_env = env_crypto.strip().lower()

        _check_sqlcipher_required(normalized_env, SQLCIPHER_AVAILABLE)

        crypto_enabled = _resolve_encryption_enabled(env_crypto, sqlcipher_available=SQLCIPHER_AVAILABLE)
        crypto_enabled = _check_plaintext_db_exists(server_state, crypto_enabled, normalized_env)
        _apply_crypto_provider(server_state, crypto_enabled, normalized_env, SQLCIPHER_AVAILABLE)

        warn_unencrypted = encryption_config.get('warn_unencrypted', True)
        if warn_unencrypted:
            storage_path = server_state.project_root / "storage" if server_state.project_root else None
            check_encryption_status(storage_path)

    except Exception as e:
        if isinstance(e, RuntimeError):
            raise
        logger.warning("Encryption init failed (non-fatal): %s", e)
        server_state.crypto_provider = None
