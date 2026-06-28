"""
────────────────────────────────────
Server Nexe
Location: tests/fixos/test_B203.py
Description: TDD fix for B203 — TextStore no fa chmod 0o700 al directori.
────────────────────────────────────
"""

import os
import stat
from pathlib import Path

import pytest


def test_text_store_dir_chmod_0o700(tmp_path):
    """B203: TextStore._init_db() ha de fer chmod 0o700 al directori pare."""
    from memory.memory.api.text_store import TextStore

    db_path = tmp_path / "subdir" / "document_texts.db"
    TextStore(db_path=db_path)

    dir_stat = db_path.parent.stat()
    actual_mode = stat.S_IMODE(dir_stat.st_mode)
    assert actual_mode == 0o700, (
        f"B203: directori {db_path.parent} té mode {oct(actual_mode)}, s'espera 0o700"
    )
