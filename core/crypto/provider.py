"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy
Location: core/crypto/provider.py
Description: CryptoProvider — AES-256-GCM encryption, HKDF key derivation.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import logging
import os
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes

from .keys import get_or_create_master_key, KEY_FILE_PATH

logger = logging.getLogger(__name__)

NONCE_SIZE = 12  # 96 bits, standard for AES-GCM
KEY_SIZE = 32    # 256 bits


class CryptoProvider:
    """
    Encryption at rest for server-nexe.

    Responsibilities:
    - Obtain/generate master key (MEK) via fallback chain
    - Derive purpose-specific data encryption keys (DEK) via HKDF-SHA256
    - Encrypt/decrypt with AES-256-GCM

    Purposes:
    - "sqlite"   → DEK for SQLCipher database
    - "sessions" → DEK for session JSON files
    - "backup"   → DEK for data export
    """

    def __init__(self, master_key: bytes | None = None, key_file_path: Path = KEY_FILE_PATH):
        if master_key is not None:
            if len(master_key) != KEY_SIZE:
                raise ValueError(f"Master key must be {KEY_SIZE} bytes, got {len(master_key)}")
            self._master_key = master_key
        else:
            self._master_key = get_or_create_master_key(key_file_path)
        self._derived_cache: dict[str, bytes] = {}

    def derive_key(self, purpose: str) -> bytes:
        """
        Derive a purpose-specific key using HKDF-SHA256.

        Args:
            purpose: Key purpose identifier (e.g. "sqlite", "sessions", "backup")

        Returns:
            32-byte derived key
        """
        if purpose in self._derived_cache:
            return self._derived_cache[purpose]

        hkdf = HKDF(
            algorithm=hashes.SHA256(),
            length=KEY_SIZE,
            salt=None,  # HKDF spec: salt=None uses a zero-filled salt
            info=purpose.encode("utf-8"),
        )
        derived = hkdf.derive(self._master_key)
        self._derived_cache[purpose] = derived
        return derived

    def encrypt(self, plaintext: bytes, purpose: str = "sessions") -> bytes:
        """
        Encrypt with AES-256-GCM.

        Format: nonce (12 bytes) || ciphertext || tag (16 bytes)

        Args:
            plaintext: Data to encrypt
            purpose: Key purpose for derivation

        Returns:
            Encrypted bytes (nonce + ciphertext + tag)
        """
        key = self.derive_key(purpose)
        nonce = os.urandom(NONCE_SIZE)
        aesgcm = AESGCM(key)
        ciphertext = aesgcm.encrypt(nonce, plaintext, None)
        return nonce + ciphertext

    def decrypt(self, data: bytes, purpose: str = "sessions") -> bytes:
        """
        Decrypt AES-256-GCM data.

        Args:
            data: nonce (12 bytes) || ciphertext || tag (16 bytes)
            purpose: Key purpose for derivation

        Returns:
            Decrypted plaintext

        Raises:
            ValueError: If data is too short
            cryptography.exceptions.InvalidTag: If decryption fails (wrong key or tampered data)
        """
        if len(data) < NONCE_SIZE + 16:  # nonce + minimum tag
            raise ValueError(f"Encrypted data too short ({len(data)} bytes)")
        key = self.derive_key(purpose)
        nonce = data[:NONCE_SIZE]
        ciphertext = data[NONCE_SIZE:]
        aesgcm = AESGCM(key)
        return aesgcm.decrypt(nonce, ciphertext, None)

    def derive_key_hex(self, purpose: str) -> str:
        """Derive key and return as hex string (useful for SQLCipher PRAGMA key)."""
        return self.derive_key(purpose).hex()
