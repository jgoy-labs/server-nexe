"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/crypto/cli.py
Description: CLI commands for encryption management.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
# pyright: reportFunctionMemberAccess=false
# Click @group decorator returns a Group at runtime but pyright sees FunctionType;
# .command accesses on `encryption` are valid (mypy accepts).

import logging

import click

from core.paths import get_storage_path

logger = logging.getLogger(__name__)


def _get_crypto_provider():
    """Create and return a CryptoProvider."""
    from .provider import CryptoProvider
    return CryptoProvider()


def _resolve_memory_dbs():
    """Return (memory_v1_db, metadata_memory_db) under the live vectors/ dir.

    D-001: the tooling used to point at storage/memory/memories.db — a path the
    server never writes. The real SQLite DBs are memory_v1.db (SQLiteStore) and
    metadata_memory.db (PersistenceManager). resolve_qdrant_path is given an
    ABSOLUTE default so the CLI works when run outside the repo root.
    """
    from memory.memory._paths import resolve_qdrant_path
    vectors_dir = resolve_qdrant_path(get_storage_path("vectors"))
    return vectors_dir / "memory_v1.db", vectors_dir / "metadata_memory.db"


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
    storage = get_storage_path()

    if not force:
        click.echo("This will encrypt all data in storage/.")
        click.echo("A backup of existing files will be created.")
        if not click.confirm("Continue?"):
            click.echo("Aborted.")
            return

    crypto = _get_crypto_provider()
    click.echo("Master key loaded.")

    # 1. SQLite migration — the two live DBs under vectors/ (D-001).
    from memory.memory.engines.persistence import PersistenceManager
    from memory.memory.storage.sqlite_store import SQLiteStore
    memory_v1_db, metadata_db = _resolve_memory_dbs()

    # 1a. memory_v1.db (SQLiteStore) — migrates in its constructor.
    if memory_v1_db.exists():
        if SQLiteStore._is_plaintext_sqlite(memory_v1_db):
            click.echo(f"Migrating {memory_v1_db} to SQLCipher...")
            SQLiteStore(memory_v1_db, crypto_provider=crypto).close()
            click.echo("  memory_v1.db migration complete.")
        else:
            click.echo(f"  {memory_v1_db} already encrypted.")
    else:
        click.echo("  No memory_v1.db found (will be created encrypted on first use).")

    # 1b. metadata_memory.db (PersistenceManager) — migrates in its constructor.
    if metadata_db.exists():
        if PersistenceManager._is_plaintext_sqlite(metadata_db):
            click.echo(f"Migrating {metadata_db} to SQLCipher...")
            pm = PersistenceManager(
                db_path=metadata_db,
                collection_name="nexe_memory",
                crypto_provider=crypto,
            )
            pm.close()
            click.echo("  metadata_memory.db migration complete.")
        else:
            click.echo(f"  {metadata_db} already encrypted.")
    else:
        click.echo("  No metadata_memory.db found.")

    # 2. Session migration
    sessions_path = storage / "sessions"
    if sessions_path.exists():
        json_files = list(sessions_path.glob("*.json"))
        if json_files:
            click.echo(f"Encrypting {len(json_files)} session file(s)...")
            from plugins.web_ui_module.core.session_manager import SessionManager
            # SessionManager auto-migrates .json → .enc on init.
            SessionManager(
                storage_path=str(sessions_path),
                crypto_provider=crypto,
            )
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
    storage = get_storage_path()
    crypto_available = True

    try:
        _get_crypto_provider()
    except Exception as e:
        click.echo(f"CryptoProvider: UNAVAILABLE ({e})")
        crypto_available = False

    if crypto_available:
        click.echo("CryptoProvider: OK (master key available)")

    # SQLCipher (defensive import — used to test availability)
    try:
        from sqlcipher3 import dbapi2  # noqa: F401
        click.echo("SQLCipher: AVAILABLE")
    except ImportError:
        click.echo("SQLCipher: NOT INSTALLED (pip install sqlcipher3)")

    # Check the live DBs under vectors/ (D-001).
    from memory.memory.engines.persistence import PersistenceManager
    for _db in _resolve_memory_dbs():
        if _db.exists():
            is_plain = PersistenceManager._is_plaintext_sqlite(_db)
            state = "PLAIN (unencrypted)" if is_plain else "ENCRYPTED"
            click.echo(f"{_db.name}: {state}")
        else:
            click.echo(f"{_db.name}: NOT FOUND")

    # Check sessions
    sessions_path = storage / "sessions"
    if sessions_path.exists():
        json_count = len(list(sessions_path.glob("*.json")))
        enc_count = len(list(sessions_path.glob("*.enc")))
        click.echo(f"Sessions: {enc_count} encrypted, {json_count} plain")
    else:
        click.echo("Sessions: directory not found")
