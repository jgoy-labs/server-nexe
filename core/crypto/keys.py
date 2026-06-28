"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/crypto/keys.py
Description: Master key management with fallback chain: file → keyring → env var → generate.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import logging
import os
import stat
import tempfile
from pathlib import Path

from core.env_utils import parse_truthy

logger = logging.getLogger(__name__)

KEYRING_SERVICE = "server-nexe"
KEYRING_USERNAME = "master-encryption-key"
ENV_VAR_NAME = "NEXE_MASTER_KEY"
KEY_SIZE = 32  # 256 bits


def _resolve_key_file_dir() -> Path:
    """Resolve master key path respecting NEXE_SIDECAR_DIR.

    En mode sidecar (Tauri injecta NEXE_SIDECAR_DIR=~/.nexe per defecte),
    usa aquest path. En standalone, fallback a ~/.nexe (compatibilitat
    amb instal·lacions prèvies del DMG / CLI).
    """
    if sidecar_dir := os.getenv("NEXE_SIDECAR_DIR"):
        return Path(sidecar_dir)
    return Path.home() / ".nexe"


def _resolve_key_file_path() -> Path:
    """Dynamic master key path (respects NEXE_SIDECAR_DIR)."""
    return _resolve_key_file_dir() / "master.key"


def _is_sidecar() -> bool:
    """True when running as the bundled Tauri sidecar (NEXE_SIDECAR=1).

    In sidecar mode the OS keyring is skipped (CRY-01): the embedded
    Developer-ID-signed Python is not in the Keychain item's trusted-application
    ACL, so a headless `keyring` access triggers a blocking macOS authorization
    dialog that the sidecar cannot answer — the boot hangs ~6 min until timeout.
    The `master.key` file is the durable anchor; the keyring is only a mirror,
    so dropping it in sidecar mode loses no durability.
    """
    # MC-087: same truthy parsing as SidecarConfig.is_sidecar (1/true/yes/...),
    # so a non-"1" spelling can't half-enable sidecar mode (CRY-01 vs CSP skew).
    return parse_truthy(os.environ.get("NEXE_SIDECAR"))


def _try_keyring_get() -> bytes | None:
    """Try to retrieve master key from OS keyring. Skipped in sidecar mode (CRY-01)."""
    if _is_sidecar():
        return None
    try:
        import keyring
        stored = keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME)
        if stored:
            return bytes.fromhex(stored)
    except Exception as e:
        logger.debug("Keyring read failed: %s", e)
    return None


def _try_keyring_set(key: bytes) -> bool:
    """Try to store master key in OS keyring. Skipped in sidecar mode (CRY-01)."""
    if _is_sidecar():
        return False
    try:
        import keyring
        keyring.set_password(KEYRING_SERVICE, KEYRING_USERNAME, key.hex())
        logger.info("Master key stored in OS keyring")
        return True
    except Exception as e:
        logger.debug("Keyring write failed: %s", e)
        return False


def _try_env_get() -> bytes | None:
    """Try to retrieve master key from environment variable."""
    value = os.getenv(ENV_VAR_NAME)
    if value:
        try:
            key = bytes.fromhex(value)
            if len(key) == KEY_SIZE:
                return key
            logger.warning("%s has wrong length (%d bytes, expected %d)", ENV_VAR_NAME, len(key), KEY_SIZE)
        except ValueError:
            logger.warning("%s is not valid hex", ENV_VAR_NAME)
    return None


def _try_file_get(path: Path | None = None) -> bytes | None:
    """Try to retrieve master key from file. Default path resolved dynamically.

    Fail-closed on present-but-unreadable (B043): if the file EXISTS but
    read_bytes() raises (I/O error, permission flip, fcntl lock, NFS/iCloud
    stall), we MUST NOT swallow it and return None. The caller treats None as
    "key absent" and generates a brand-new key, which derives a different
    SQLCipher DEK and quarantines the existing encrypted DB as .unrecoverable-*
    (silent data loss). A present-but-unreadable key is a transient/permission
    fault, not an absent key, so re-raise and refuse to continue. This mirrors
    the write path, which already fails closed (see get_or_create_master_key).

    Distinct cases:
    - absent (not path.exists())               → return None (legit first boot)
    - present but read_bytes() raises (OSError) → raise (fail-closed)  [B043]
    - present, readable, wrong length          → warn + None (corrupt content,
                                                  separate decision; kept as-is)
    """
    if path is None:
        path = _resolve_key_file_path()
    if not path.exists():
        return None
    try:
        key = path.read_bytes()
    except OSError as e:
        raise RuntimeError(
            f"Master key file {path} exists but is unreadable ({e}). Refusing "
            "to continue: treating it as absent would generate a new key and "
            "quarantine the existing encrypted database. Fix the file "
            "permissions / release the lock / let the sync settle, then restart."
        ) from e
    if len(key) == KEY_SIZE:
        return key
    logger.warning("Key file %s has wrong length (%d bytes)", path, len(key))
    return None


def _try_file_set(key: bytes, path: Path | None = None) -> bool:
    """Store master key to file with restricted permissions (600).

    Bug 8 fix — TOCTOU window: previously the key was written with
    default umask (typically 644) and then chmod'd to 600. During that
    window the key was world-readable. We now create the file via
    os.open() with O_CREAT|O_EXCL|O_WRONLY and mode 0o600 so the file
    is born with restrictive permissions and never exists with broader
    ones. If the file already exists (legitimate reuse case), we
    overwrite atomically via a temp file created the same secure way.
    """
    if path is None:
        path = _resolve_key_file_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Restrict directory permissions too (700) — best effort. On noexec
        # mounts, ACL-restricted filesystems, or sandboxed runtimes the chmod
        # can fail. The file itself is still created 0o600 via os.open below,
        # so we don't abort — but we log a WARNING so operators notice that
        # the enclosing directory may have broader permissions than expected.
        try:
            path.parent.chmod(stat.S_IRWXU)  # 0o700
        except Exception as e:
            logger.warning(
                "chmod 0o700 failed on key dir %s: %s (key file perms still 0o600)",
                path.parent,
                e,
            )

        # Write atomically to a sibling temp file with restrictive mode,
        # so we never expose the key with relaxed permissions. `mkstemp`
        # returns a unique name per call, which also protects against
        # same-process concurrent calls (two threads syncing the MEK after
        # reading it from the keyring) that would otherwise collide on a
        # shared PID-derived path.
        fd, tmp_name = tempfile.mkstemp(
            prefix=".master.key.tmp.",
            dir=str(path.parent),
        )
        tmp_path = Path(tmp_name)
        try:
            # mkstemp on POSIX returns 0o600 already, but set it explicitly
            # for cross-platform safety.
            os.chmod(tmp_path, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(key)
                f.flush()
                os.fsync(f.fileno())
        except Exception:
            # If write failed, ensure tmp is removed
            try:
                tmp_path.unlink()
            except FileNotFoundError:
                pass
            raise

        # Atomic replace — preserves the 0o600 permissions of tmp_path
        os.replace(str(tmp_path), str(path))

        logger.info("Master key stored at %s (permissions 600)", path)
        return True
    except Exception as e:
        logger.error("Failed to write key file: %s", e)
        return False


def get_or_create_master_key(key_file_path: Path | None = None) -> bytes:
    """
    Retrieve or generate the master encryption key (MEK).

    Fallback chain (fix bug #19b, pre-release v1.0):

    1. Key file at ~/.nexe/master.key (permissions 600) — primary, persistent
    2. OS keyring (macOS Keychain / Linux Secret Service / Windows Credential Locker)
    3. NEXE_MASTER_KEY environment variable
    4. Generate new key → store to BOTH file + keyring (dual-write)

    Why file-first:
    Before this fix, a single source (Keychain) was the primary store. When the
    Keychain got invalidated (OS upgrade, user reset, sandboxing change), a
    brand-new key was generated, silently rendering every existing .enc session
    and SQLCipher DB unreadable. For an autonomous agent that reboots on its
    own, losing memory is unacceptable. The file is the durable anchor; the
    keyring is a convenience mirror.

    The key is ALWAYS kept in both sources: generating writes to both; loading
    from the keyring (with no file present) synchronises a copy to the file.

    Returns:
        32-byte master key
    """
    # resolve path dynamically if not passed (respects NEXE_SIDECAR_DIR)
    if key_file_path is None:
        key_file_path = _resolve_key_file_path()
    # 1. File (primary persistent store)
    key = _try_file_get(key_file_path)
    if key:
        logger.debug("Master key loaded from %s", key_file_path)
        # Opportunistic: mirror to keyring if empty, so future reads are fast
        # and Keychain-based Spotlight/Sharing remain consistent.
        if _try_keyring_get() is None:
            _try_keyring_set(key)
        return key

    # 2. Keyring
    key = _try_keyring_get()
    if key:
        logger.debug("Master key loaded from OS keyring")
        # Synchronise to file so a future Keychain reset does NOT regenerate.
        _try_file_set(key, key_file_path)
        return key

    # 3. Env var (for headless CI / containerised runs)
    key = _try_env_get()
    if key:
        logger.debug("Master key loaded from %s", ENV_VAR_NAME)
        return key

    # 4. Generate new — dual-write to file + keyring. File is mandatory;
    # keyring is best-effort (some environments lack a secret service).
    key = os.urandom(KEY_SIZE)
    logger.info("Generated new master encryption key")
    # fail-fast on file persistence failure for NEW keys.
    # Returning the key without persisting it would leave the next boot
    # generating yet another fresh key — every record we encrypt now becomes
    # un-decryptable after restart. Better to refuse to start than to lose data
    # silently. (Reads in steps 1-3 don't fail-fast because the key already
    # exists somewhere durable; only the brand-new write path is critical.)
    if not _try_file_set(key, key_file_path):
        raise RuntimeError(
            f"Failed to persist newly-generated master key to {key_file_path}. "
            "Refusing to continue — encrypting data with a non-persisted key "
            "would render it unrecoverable after restart. Check directory "
            "permissions, free disk space, and filesystem read-only flags."
        )
    _try_keyring_set(key)
    return key
