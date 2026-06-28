"""
────────────────────────────────────
Server Nexe
Location: tests/fixos/test_B235.py
Description: TDD fix for B235 — el manifest del mòdul CLI anuncia una UI
             web inexistent (/ui-control/clis). MODULE_METADATA ha de declarar
             ui_available=False i no exposar ui_path.
────────────────────────────────────
"""

import importlib


def _get_metadata():
    import core.cli.manifest as m
    importlib.reload(m)
    return m.MODULE_METADATA


def test_module_metadata_does_not_advertise_phantom_ui():
    """
    B235: MODULE_METADATA no ha d'anunciar ui_available=True per a una ruta
    que no existeix com a endpoint servit.
    """
    meta = _get_metadata()
    assert meta.get("ui_available") is not True, (
        "MODULE_METADATA anuncia ui_available=True però la ruta /ui-control/clis no existeix"
    )


def test_module_metadata_does_not_expose_phantom_ui_path():
    """
    B235: MODULE_METADATA no ha d'incloure ui_path si la UI no existeix.
    Si ui_available és False/absent, ui_path no té sentit i indueix a error.
    """
    meta = _get_metadata()
    # Si ui_available és False (o absent), ui_path ha de ser absent o None
    if not meta.get("ui_available"):
        ui_path = meta.get("ui_path")
        assert ui_path is None or ui_path == "", (
            f"MODULE_METADATA té ui_path='{ui_path}' però ui_available és False/absent"
        )
