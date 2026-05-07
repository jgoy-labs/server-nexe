"""
────────────────────────────────────
Server Nexe
Location: tests/test_integrity_pins_visibility.py
Description: B5 (audit r4) — real visibility of the runtime WARNING
             when `MODEL_WEIGHT_SHA256` loads a `None` pin, and documentary
             guards that keep the catalog, the module header comment,
             and the CHANGELOG in sync.

             Three invariants:
             1. `verify_sha256(expected=None, allow_missing=True)` returns
                False and emits an explicit WARNING (not silent).
             2. The file `installer/installer_catalog_data.py` explicitly
                documents the current state (all `None`) in its header.
             3. If someone starts populating pins, the CHANGELOG must reflect
                the progress (failsafe against doc/code drift).
────────────────────────────────────
"""

from __future__ import annotations

import logging
from pathlib import Path

from core.integrity.hashing import verify_sha256
from installer.installer_catalog_data import MODEL_WEIGHT_SHA256

REPO_ROOT = Path(__file__).resolve().parent.parent
CATALOG_PATH = REPO_ROOT / "installer" / "installer_catalog_data.py"
CHANGELOG_PATH = REPO_ROOT / "CHANGELOG.md"


def test_verify_sha256_emits_warning_when_pin_is_none(caplog):
    """B5: pin=None must emit an explicit WARNING (not silent)."""
    fake_actual = "a" * 64  # valid SHA256 hex
    with caplog.at_level(logging.WARNING, logger="core.integrity.hashing"):
        result = verify_sha256(
            actual=fake_actual,
            expected=None,
            artifact="test:fake-model",
            allow_missing=True,
        )
    assert result is False, "pin=None must return False (degraded)"
    warns = [r for r in caplog.records if r.levelno == logging.WARNING]
    messages = [r.getMessage() for r in warns]
    assert any("no SHA256 pin" in m for m in messages), f"WARNING 'no SHA256 pin' not emitted. Logs: {messages}"


def test_catalog_all_pins_are_none_is_documented():
    """B5: if ALL pins are None, there must be a STATUS comment in the file."""
    text = CATALOG_PATH.read_text(encoding="utf-8")
    assert "STATUS v1.0.3-beta" in text and "ALL VALUES BELOW ARE None" in text, (
        "Transparency header comment for pins=None is mandatory (installer/installer_catalog_data.py)"
    )


def test_catalog_pin_count_consistency():
    """B5: CHANGELOG says 26 entries; verify that reality matches.

    If in the future someone starts populating pins (v1.0.4-beta C19), the CHANGELOG
    must be updated in parallel — failsafe against doc/code drift.
    """
    actual = len(MODEL_WEIGHT_SHA256)
    assert actual >= 20, f"Catalog unexpectedly small ({actual} entries) — CHANGELOG says ~26"

    non_none = sum(1 for v in MODEL_WEIGHT_SHA256.values() if v is not None)
    if non_none > 0:
        # If someone starts populating — ensure the CHANGELOG documents it.
        ch = CHANGELOG_PATH.read_text(encoding="utf-8")
        assert "Status at" in ch and ("populated" in ch.lower() or "pinned" in ch.lower()), (
            "If you start populating pins, also update the CHANGELOG "
            "(section 'Status at v1.0.X-beta' with the new pin count)"
        )
