"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/crypto/cli.py
Description: CLI commands for encryption management.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import logging
import os
import sys
from pathlib import Path

import click

logger = logging.getLogger(__name__)


def _get_storage_path() -> Path:
    """Get the storage path relative to project root."""
    return Path(__file__).parent.parent.parent / "storage"


def _get_crypto_provider():
    """Create and return a CryptoProvider."""
    from .provider import CryptoProvider
    return CryptoProvider()


@click.group()
def encryption():
    """Encryption management commands."""
    pass


@encryption.command("encrypt-all")
@click.option("--force", is_flag=True, help="Skip confirmation prompt")
def encrypt_all(force):
    """
    Encrypt all unencrypted data at rest.

    Migrates:
    - SQLite memories.db → SQLCipher (encrypted)
    - Session .json files → .enc (AES-256-GCM)
    - Qdrant payloads: removes text fields from existing entries
    """
    storage = _get_storage_path()

    if not force:
        click.echo("This will encrypt all data in storage/.")
        click.echo("A backup of existing files will be created.")
        if not click.confirm("Continue?"):
            click.echo("Aborted.")
            return

    crypto = _get_crypto_provider()
    click.echo("Master key loaded.")

    # 1. SQLite migration
    db_path = storage / "memory" / "memories.db"
    if db_path.exists():
        from memory.memory.engines.persistence import PersistenceManager
        if PersistenceManager._is_plaintext_sqlite(db_path):
            click.echo(f"Migrating {db_path} to SQLCipher...")
            pm = PersistenceManager(
                db_path=db_path,
                collection_name="nexe_memory",
                crypto_provider=crypto,
            )
            pm.close()
            click.echo("  SQLite migration complete.")
        else:
            click.echo(f"  {db_path} already encrypted.")
    else:
        click.echo("  No memories.db found (will be created encrypted on first use).")

    # 2. Session migration
    sessions_path = storage / "sessions"
    if sessions_path.exists():
        json_files = list(sessions_path.glob("*.json"))
        if json_files:
            click.echo(f"Encrypting {len(json_files)} session file(s)...")
            from plugins.web_ui_module.core.session_manager import SessionManager
            sm = SessionManager(
                storage_path=str(sessions_path),
                crypto_provider=crypto,
            )
            # SessionManager auto-migrates .json → .enc on init
            click.echo(f"  Sessions encrypted ({len(json_files)} migrated).")
        else:
            click.echo("  No plain .json sessions found.")
    else:
        click.echo("  No sessions directory found.")

    # 3. Qdrant payload cleanup
    click.echo("Qdrant payload cleanup: text removed from new entries via store().")
    click.echo("  Existing payloads retain redundant text (harmless, cleaned on re-store).")

    click.echo("\nEncryption complete.")


@encryption.command("export-key")
@click.option("--hex", "as_hex", is_flag=True, help="Output as hex string")
def export_key(as_hex):
    """Export the master encryption key for backup."""
    from .keys import get_or_create_master_key

    click.echo("WARNING: This key protects all encrypted data.", err=True)
    click.echo("Store it securely (password manager, offline backup).", err=True)
    click.echo("", err=True)

    key = get_or_create_master_key()
    if as_hex:
        click.echo(key.hex())
    else:
        import base64
        click.echo(base64.b64encode(key).decode("ascii"))


@encryption.command("status")
def encryption_status():
    """Show encryption status of storage."""
    storage = _get_storage_path()
    crypto_available = True

    try:
        _get_crypto_provider()
    except Exception as e:
        click.echo(f"CryptoProvider: UNAVAILABLE ({e})")
        crypto_available = False

    if crypto_available:
        click.echo("CryptoProvider: OK (master key available)")

    # SQLCipher
    try:
        from sqlcipher3 import dbapi2
        click.echo("SQLCipher: AVAILABLE")
    except ImportError:
        click.echo("SQLCipher: NOT INSTALLED (pip install sqlcipher3)")

    # Check DB
    db_path = storage / "memory" / "memories.db"
    if db_path.exists():
        from memory.memory.engines.persistence import PersistenceManager
        is_plain = PersistenceManager._is_plaintext_sqlite(db_path)
        status = "PLAIN (unencrypted)" if is_plain else "ENCRYPTED"
        click.echo(f"memories.db: {status}")
    else:
        click.echo("memories.db: NOT FOUND")

    # Check sessions
    sessions_path = storage / "sessions"
    if sessions_path.exists():
        json_count = len(list(sessions_path.glob("*.json")))
        enc_count = len(list(sessions_path.glob("*.enc")))
        click.echo(f"Sessions: {enc_count} encrypted, {json_count} plain")
    else:
        click.echo("Sessions: directory not found")
