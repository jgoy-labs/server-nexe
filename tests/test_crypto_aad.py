"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/test_crypto_aad.py
Description: B4 (auditoria r4) — AES-GCM AAD binding for encrypted sessions.

Tests verify that AAD (Additional Authenticated Data) binds the ciphertext
to a context (session_id), preventing swap attacks where an attacker with
disk access renames `A.enc` ↔ `B.enc`.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import pytest
from cryptography.exceptions import InvalidTag

from core.crypto.provider import CryptoProvider


@pytest.fixture
def crypto():
    """Crypto provider with a fixed master key for deterministic tests."""
    return CryptoProvider(master_key=b"\x00" * 32)


def test_encrypt_decrypt_with_aad(crypto):
    """B4: encrypt with AAD and decrypt with the same AAD recovers plaintext."""
    plaintext = b"hello world"
    aad = b"session-abc-123"
    ct = crypto.encrypt(plaintext, aad=aad)
    pt = crypto.decrypt(ct, aad=aad)
    assert pt == plaintext


def test_aad_binds_ciphertext_to_context(crypto):
    """B4: encrypting with AAD=A and decrypting with AAD=B raises InvalidTag (swap attack blocked)."""
    plaintext = b"sessio A: contingut secret"
    aad_a = b"session-A"
    aad_b = b"session-B"
    ct = crypto.encrypt(plaintext, aad=aad_a)
    with pytest.raises(InvalidTag):
        crypto.decrypt(ct, aad=aad_b)


def test_wrong_aad_fails(crypto):
    """B4: ciphertext encrypted with AAD cannot be decrypted with aad=None."""
    plaintext = b"data"
    ct = crypto.encrypt(plaintext, aad=b"some-aad")
    with pytest.raises(InvalidTag):
        crypto.decrypt(ct, aad=None)
    # Also: ciphertext encrypted without AAD cannot be decrypted with an AAD.
    ct2 = crypto.encrypt(plaintext)  # default aad=None
    with pytest.raises(InvalidTag):
        crypto.decrypt(ct2, aad=b"unexpected-aad")


def test_decrypt_old_data_without_aad_still_works(crypto):
    """B4: encrypt without AAD + decrypt without AAD keeps working
    (backward compat for non-session purposes: text_store, persistence, memory_api, CLI).
    """
    plaintext = b"non-session data"
    ct = crypto.encrypt(plaintext)  # default aad=None
    pt = crypto.decrypt(ct)         # default aad=None
    assert pt == plaintext


def test_session_swap_attack_blocked(tmp_path, crypto):
    """B4 (integration): renaming A.enc → B.enc on disk is detected at load time.

    AAD = session_id binds the ciphertext to the filename. After a swap, the
    AAD passed to decrypt (= filename stem) no longer matches the AAD used at
    encrypt → AESGCM raises InvalidTag → SessionManager catches it, increments
    `_corrupted_sessions_count`, and the swapped sessions are NOT loaded.
    """
    from plugins.web_ui_module.core.session_manager import SessionManager, ChatSession

    storage = tmp_path / "sessions"
    storage.mkdir()

    sm = SessionManager(storage_path=str(storage), crypto_provider=crypto)

    sa = ChatSession(session_id="sess-A")
    sb = ChatSession(session_id="sess-B")
    sm._sessions[sa.id] = sa
    sm._sessions[sb.id] = sb
    sm._save_session_to_disk(sa)
    sm._save_session_to_disk(sb)

    # Swap attack: A.enc ↔ B.enc
    (storage / "sess-A.enc").rename(storage / "sess-A.enc.bak")
    (storage / "sess-B.enc").rename(storage / "sess-A.enc")
    (storage / "sess-A.enc.bak").rename(storage / "sess-B.enc")

    # Reload from disk: AAD mismatch must trigger InvalidTag → corrupted counter.
    sm2 = SessionManager(storage_path=str(storage), crypto_provider=crypto)
    assert sm2._corrupted_sessions_count == 2, (
        f"Expected 2 corrupted (both swapped files), got {sm2._corrupted_sessions_count}"
    )
    assert "sess-A" not in sm2._sessions and "sess-B" not in sm2._sessions, (
        "Swapped sessions must not be loaded into memory"
    )
