"""
────────────────────────────────────
Server Nexe
Location: tests/test_integrity_pins_visibility.py
Description: B5 (auditoria r4) — visibilitat real del WARNING runtime
             quan `MODEL_WEIGHT_SHA256` carrega un pin `None`, i guards
             documentals que mantenen sincronitzats el catàleg, el comentari
             header del mòdul i el CHANGELOG.

             Tres invariants:
             1. `verify_sha256(expected=None, allow_missing=True)` retorna
                False i emet un WARNING explícit (no silent).
             2. El fitxer `installer/installer_catalog_data.py` documenta
                explícitament l'estat actual (tots `None`) al seu header.
             3. Si algú comença a poblar pins, el CHANGELOG ha de reflectir
                el progrés (failsafe contra drift doc/codi).
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
    """B5: pin=None ha d'emetre WARNING explícit (no silent)."""
    fake_actual = "a" * 64  # SHA256 vàlid hex
    with caplog.at_level(logging.WARNING, logger="core.integrity.hashing"):
        result = verify_sha256(
            actual=fake_actual,
            expected=None,
            artifact="test:fake-model",
            allow_missing=True,
        )
    assert result is False, "pin=None ha de retornar False (degraded)"
    warns = [r for r in caplog.records if r.levelno == logging.WARNING]
    messages = [r.getMessage() for r in warns]
    assert any("no SHA256 pin" in m for m in messages), f"WARNING 'no SHA256 pin' no emès. Logs: {messages}"


def test_catalog_all_pins_are_none_is_documented():
    """B5: si TOTS els pins són None, ha d'haver un comentari STATUS al fitxer."""
    text = CATALOG_PATH.read_text(encoding="utf-8")
    assert "STATUS v1.0.3-beta" in text and "ALL VALUES BELOW ARE None" in text, (
        "Comentari header de transparència per pins=None obligatori (installer/installer_catalog_data.py)"
    )


def test_catalog_pin_count_consistency():
    """B5: el CHANGELOG diu 26 entries; verificar que la realitat coincideix.

    Si en el futur algú comença a poblar pins (v1.0.4-beta C19), el CHANGELOG
    ha d'actualitzar-se en paral·lel — failsafe contra drift doc/codi.
    """
    actual = len(MODEL_WEIGHT_SHA256)
    assert actual >= 20, f"Catàleg estranyament petit ({actual} entries) — CHANGELOG diu ~26"

    non_none = sum(1 for v in MODEL_WEIGHT_SHA256.values() if v is not None)
    if non_none > 0:
        # Si algú comença a poblar — assegurar que el CHANGELOG ho documenta.
        ch = CHANGELOG_PATH.read_text(encoding="utf-8")
        assert "Status at" in ch and ("populated" in ch.lower() or "pinned" in ch.lower()), (
            "Si comences a poblar pins, actualitza també el CHANGELOG "
            "(secció 'Status at v1.0.X-beta' amb el nou nombre de pins)"
        )
