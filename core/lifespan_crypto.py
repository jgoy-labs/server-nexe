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


async def _startup_encryption(server_state) -> None:
    """Initialize encryption-at-rest (opt-in). Modifies server_state.crypto_provider."""
    from core.lifespan import _resolve_encryption_enabled  # avoid circular at module level

    try:
        from core.crypto import CryptoProvider, check_encryption_status

        encryption_config = server_state.config.get('security', {}).get('encryption', {})

        env_crypto = os.environ.get('NEXE_ENCRYPTION_ENABLED', 'auto')
        from memory.memory.engines.persistence import SQLCIPHER_AVAILABLE
        crypto_enabled = _resolve_encryption_enabled(env_crypto, sqlcipher_available=SQLCIPHER_AVAILABLE)

        normalized_env = env_crypto.strip().lower()
        if normalized_env == 'true' and not SQLCIPHER_AVAILABLE:
            raise RuntimeError(
                "Encryption at rest requested (NEXE_ENCRYPTION_ENABLED=true) "
                "but sqlcipher3 is not installed. The server will NOT start to avoid "
                "a false sense of security. Either:\n"
                "  (1) Install sqlcipher3: pip install sqlcipher3-binary\n"
                "  (2) Disable encryption: NEXE_ENCRYPTION_ENABLED=false"
            )

        # P1-D: in auto mode, if plain-text data already exists do NOT enable encryption
        if crypto_enabled and normalized_env in ('', 'auto'):
            storage_path_check = server_state.project_root / "storage" if server_state.project_root else None
            if storage_path_check:
                db_path = storage_path_check / "memory" / "memories.db"
                if db_path.exists():
                    try:
                        with open(db_path, 'rb') as _f:
                            _header = _f.read(16)
                        if _header == b'SQLite format 3\x00':
                            crypto_enabled = False
                            logger.warning(
                                "Encryption auto=ON skipped: existing plain-text memories.db detected. "
                                "Run 'nexe encryption encrypt-all' to migrate data, then restart. "
                                "Set NEXE_ENCRYPTION_ENABLED=false to suppress this warning."
                            )
                    except Exception:  # nosec B110
                        pass

        if crypto_enabled:
            server_state.crypto_provider = CryptoProvider()
            logger.info("Encryption at rest: ENABLED (AES-256-GCM)")
        elif normalized_env in ('', 'auto') and not SQLCIPHER_AVAILABLE:
            from core.crypto import format_plaintext_startup_banner
            logger.warning(format_plaintext_startup_banner())
        else:
            logger.info("Encryption at rest: disabled")

        warn_unencrypted = encryption_config.get('warn_unencrypted', True)
        if warn_unencrypted:
            storage_path = server_state.project_root / "storage" if server_state.project_root else None
            check_encryption_status(storage_path)

    except Exception as e:
        if isinstance(e, RuntimeError):
            raise
        logger.warning("Encryption init failed (non-fatal): %s", e)
        server_state.crypto_provider = None
