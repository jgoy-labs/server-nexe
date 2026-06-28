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

from core.config import _resolve_encryption_enabled

logger = logging.getLogger(__name__)


def _resolve_storage_root(server_state):
    """Resolve the storage root honouring sidecar mode.

    In sidecar mode the storage tree (memory/, vectors/, etc.) lives under
    SidecarConfig.data_dir — typically ~/.nexe/data — not inside the Tauri
    bundle's project_root/storage which is read-only and would mask user
    data. Standalone mode keeps the legacy project_root/storage layout.

    Returns None if neither resolution succeeds (callers must handle).
    """
    try:
        from core.sidecar_config import get_sidecar_config
        cfg = get_sidecar_config()
        if cfg.is_sidecar:
            return cfg.data_dir
    except Exception as exc:
        logger.debug(
            "SidecarConfig unavailable in _resolve_storage_root; "
            "falling back to project_root/storage: %s",
            exc,
        )
    return server_state.project_root / "storage" if server_state.project_root else None


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
    """In auto mode, LOG (never disable) when a plaintext memory DB is present.

    D-001/Decision A (2026-06-06): the SQLite stores now auto-migrate a plaintext
    DB to SQLCipher on first open (SQLiteStore._migrate_to_encrypted /
    SqliteStorageMixin._migrate_to_encrypted), so encryption must stay ENABLED for
    the migration to run. Disabling it here would (a) skip the migration and leave
    PII in clear, and (b) on the next boot open the ALREADY-encrypted
    metadata_memory.db without a key → "file is not a database" → broken memory
    subsystem. The previous code pointed at storage/memory/memories.db (a path the
    server never writes), so it never fired; it now inspects the real vectors/ DBs
    and only surfaces an informational log. Returns crypto_enabled unchanged.
    """
    if not (crypto_enabled and normalized_env in ('', 'auto')):
        return crypto_enabled

    storage_path_check = _resolve_storage_root(server_state)
    if not storage_path_check:
        return crypto_enabled

    try:
        from memory.memory._paths import resolve_qdrant_path
        vectors_dir = resolve_qdrant_path(storage_path_check / "vectors")
    except Exception:  # nosec B110
        vectors_dir = storage_path_check / "vectors"

    for name in ("memory_v1.db", "metadata_memory.db"):
        db_path = vectors_dir / name
        try:
            if not db_path.exists() or db_path.stat().st_size == 0:
                continue
            with open(db_path, 'rb') as _f:
                _header = _f.read(16)
            if _header == b'SQLite format 3\x00':
                logger.info(
                    "Encryption auto=ON: %s is plaintext and will be migrated to "
                    "SQLCipher on first open (a verified plaintext backup is removed "
                    "after migration).", name,
                )
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
    # B044: track whether encryption was actually requested so the outer handler
    # fails CLOSED when init breaks. Silently nulling crypto_provider after the
    # user asked for encryption would boot in plaintext on a fresh install,
    # writing PII unencrypted. Only crypto-disabled boots may swallow init errors.
    crypto_enabled = False
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

        # The informational status check must never undo the crypto provider we
        # just set: a failure here would otherwise fall into the outer handler and
        # null crypto_provider, leaving an already-encrypted DB to be opened
        # without a key on the next boot ("file is not a database").
        warn_unencrypted = encryption_config.get('warn_unencrypted', True)
        if warn_unencrypted:
            try:
                storage_path = _resolve_storage_root(server_state)
                check_encryption_status(storage_path)
            except Exception as warn_exc:  # nosec B110: informational only, must not disable crypto
                logger.debug("check_encryption_status failed (non-fatal): %s", warn_exc)

    except Exception as e:
        # Fail-closed when encryption was requested: re-raise ANY exception (not
        # just RuntimeError) so we never boot in plaintext when crypto was asked
        # for (B044). Swallow only when crypto was off (best-effort init).
        if isinstance(e, RuntimeError) or crypto_enabled:
            raise
        logger.warning("Encryption init failed (non-fatal): %s", e)
        server_state.crypto_provider = None
