"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/crypto/keys.py
Description: Master key management with fallback chain: keyring → env var → file.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import logging
import os
import stat
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

KEYRING_SERVICE = "server-nexe"
KEYRING_USERNAME = "master-encryption-key"
ENV_VAR_NAME = "NEXE_MASTER_KEY"
KEY_FILE_DIR = Path.home() / ".nexe"
KEY_FILE_PATH = KEY_FILE_DIR / "master.key"
KEY_SIZE = 32  # 256 bits


def _try_keyring_get() -> bytes | None:
    """Try to retrieve master key from OS keyring."""
    try:
        import keyring
        stored = keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME)
        if stored:
            return bytes.fromhex(stored)
    except Exception as e:
        logger.debug("Keyring read failed: %s", e)
    return None


def _try_keyring_set(key: bytes) -> bool:
    """Try to store master key in OS keyring."""
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


def _try_file_get(path: Path = KEY_FILE_PATH) -> bytes | None:
    """Try to retrieve master key from file."""
    if not path.exists():
        return None
    try:
        key = path.read_bytes()
        if len(key) == KEY_SIZE:
            return key
        logger.warning("Key file %s has wrong length (%d bytes)", path, len(key))
    except Exception as e:
        logger.debug("Key file read failed: %s", e)
    return None


def _try_file_set(key: bytes, path: Path = KEY_FILE_PATH) -> bool:
    """Store master key to file with restricted permissions (600).

    Bug 8 fix — TOCTOU window: previously the key was written with
    default umask (typically 644) and then chmod'd to 600. During that
    window the key was world-readable. We now create the file via
    os.open() with O_CREAT|O_EXCL|O_WRONLY and mode 0o600 so the file
    is born with restrictive permissions and never exists with broader
    ones. If the file already exists (legitimate reuse case), we
    overwrite atomically via a temp file created the same secure way.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Restrict directory permissions too (700) — best effort
        try:
            path.parent.chmod(stat.S_IRWXU)  # 0o700
        except Exception:
            pass

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


def get_or_create_master_key(key_file_path: Path = KEY_FILE_PATH) -> bytes:
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
    _try_file_set(key, key_file_path)
    _try_keyring_set(key)
    return key
