"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/crypto/__init__.py
Description: Encryption at rest — key management, AES-256-GCM, key derivation.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from .provider import CryptoProvider

__all__ = [
    "CryptoProvider",
    "check_encryption_status",
    "format_plaintext_startup_banner",
]


def format_plaintext_startup_banner() -> str:
    """Return a multi-line banner announcing that encryption at rest is off.

    Single-line `logger.warning(...)` lines get buried in startup logs.
    This banner is loud on purpose: when `NEXE_ENCRYPTION_ENABLED=auto`
    and `sqlcipher3` is not installed, server-nexe falls back to plaintext
    storage (memory DB, session `.enc`→`.json`, RAG text). Operators who
    store sensitive data deserve to notice.
    """
    sep = "═" * 66
    return (
        "\n"
        f"{sep}\n"
        "⚠️  PLAINTEXT MODE — ENCRYPTION AT REST IS DISABLED\n"
        f"{sep}\n"
        "  sqlcipher3 is not installed. All stored data (memories,\n"
        "  sessions, RAG documents) is written UNENCRYPTED to disk.\n"
        "\n"
        "  Require encryption (server refuses to start without it):\n"
        "      pip install sqlcipher3-binary\n"
        "      export NEXE_ENCRYPTION_ENABLED=true\n"
        "\n"
        "  Silence this notice for dev/CI (stay plaintext intentionally):\n"
        "      export NEXE_ENCRYPTION_ENABLED=false\n"
        f"{sep}\n"
    )


def check_encryption_status(storage_path=None):
    """
    Check for unencrypted data and log a warning if found.
    Call at server startup.
    """
    import logging
    from pathlib import Path

    logger = logging.getLogger(__name__)

    if storage_path is None:
        storage_path = Path(__file__).parent.parent.parent / "storage"
    else:
        storage_path = Path(storage_path)

    warnings = []

    # Check the real SQLite DBs under vectors/ (D-001: storage/memory/memories.db
    # was a phantom path the server never writes).
    try:
        from memory.memory._paths import resolve_qdrant_path
        vectors_dir = resolve_qdrant_path(storage_path / "vectors")
    except Exception:  # nosec B110: best-effort resolution; fall back to legacy layout
        vectors_dir = storage_path / "vectors"
    for _db_name in ("memory_v1.db", "metadata_memory.db"):
        db_path = vectors_dir / _db_name
        if not db_path.exists():
            continue
        try:
            with open(db_path, 'rb') as f:
                header = f.read(16)
            if header == b'SQLite format 3\x00':
                warnings.append(f"{_db_name} is unencrypted")
        except (PermissionError, OSError) as e:  # nosec B110: best-effort SQLite header probe at startup
            logger.debug("check_encryption_status: could not read %s: %s", db_path, e)

    # Check sessions
    sessions_path = storage_path / "sessions"
    if sessions_path.exists():
        json_count = len(list(sessions_path.glob("*.json")))
        if json_count > 0:
            warnings.append(f"{json_count} session file(s) are unencrypted (.json)")

    if warnings:
        logger.warning(
            "Unencrypted data detected in storage/: %s. "
            "Encryption is auto-enabled when sqlcipher3 is available. "
            "To force encryption: set NEXE_ENCRYPTION_ENABLED=true in .env. "
            "To suppress this warning: set warn_unencrypted=false in server.toml [security.encryption]. "
            "To encrypt existing data: run 'nexe encryption encrypt-all'.",
            "; ".join(warnings)
        )
