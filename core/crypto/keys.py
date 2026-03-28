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
    """Store master key to file with restricted permissions (600)."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(key)
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0o600
        logger.info("Master key stored at %s (permissions 600)", path)
        return True
    except Exception as e:
        logger.error("Failed to write key file: %s", e)
        return False


def get_or_create_master_key(key_file_path: Path = KEY_FILE_PATH) -> bytes:
    """
    Retrieve or generate the master encryption key (MEK).

    Fallback chain:
    1. OS keyring (macOS Keychain / Linux Secret Service / Windows Credential Locker)
    2. NEXE_MASTER_KEY environment variable
    3. Key file at ~/.nexe/master.key (permissions 600)
    4. Generate new key → store in keyring (or file as fallback)

    Returns:
        32-byte master key
    """
    # 1. Keyring
    key = _try_keyring_get()
    if key:
        logger.debug("Master key loaded from OS keyring")
        return key

    # 2. Env var
    key = _try_env_get()
    if key:
        logger.debug("Master key loaded from %s", ENV_VAR_NAME)
        return key

    # 3. File
    key = _try_file_get(key_file_path)
    if key:
        logger.debug("Master key loaded from %s", key_file_path)
        return key

    # 4. Generate new
    key = os.urandom(KEY_SIZE)
    logger.info("Generated new master encryption key")

    # Try to store: keyring first, file as fallback
    if not _try_keyring_set(key):
        _try_file_set(key, key_file_path)

    return key
