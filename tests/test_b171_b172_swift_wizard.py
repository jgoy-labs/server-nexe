"""
────────────────────────────────────
Server Nexe — test
Author: Jordi Goy
Location: tests/test_b171_b172_swift_wizard.py
Description: B171 + B172 — fixos del wizard Swift d'instal·lació.

Aquests tests llegeixen el codi font Swift REAL i verifiquen l'operador / la
crida exactes del fix. Detecten la regressió (red→green) sense replicar la
lògica en Python (que seria test-theatre) ni compilar Swift. La verificació en
runtime (un model de frontera realment seleccionable / el botó cancel·lant el
subprocés en viu) requeriria un UITest amb toolchain Swift — diferit.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from pathlib import Path

SWIFT_DIR = (
    Path(__file__).resolve().parent.parent
    / "installer" / "swift-wizard" / "Sources" / "InstallNexe"
)


def test_b171_model_picker_uses_strict_greater_than():
    """B171: un model al seu tier exacte (ramGB == 75% de la RAM) ha de ser
    seleccionable → la regla 'massa gran' ha de ser '>' estricte, no '>='."""
    src = (SWIFT_DIR / "ModelPickerView.swift").read_text()
    line = next(
        l for l in src.splitlines() if "tooLarge" in l and "ramGB" in l and "0.75" in l
    )
    assert ">=" not in line, f"B171: la regla encara bloqueja la frontera amb '>=': {line.strip()}"
    assert ">" in line, f"B171: falta l'operador de comparació: {line.strip()}"


def test_b172_cancel_button_cancels_install_before_terminate():
    """B172: el botó destructiu de l'alerta de cancel·lació ha de cridar
    engine.cancelInstall() ABANS de terminar l'app, perquè no deixi el
    subprocés d'instal·lació orfe."""
    src = (SWIFT_DIR / "InstallerWizardView.swift").read_text()
    start = src.index("isPresented: $showCancelAlert")
    block = src[start:start + 400]
    assert "cancelInstall()" in block, "B172: el botó cancel no atura la instal·lació (subprocés orfe)"
    assert "terminate" in block, "B172: no trobo el terminate al bloc del botó cancel"
    assert block.index("cancelInstall()") < block.index("terminate"), \
        "B172: cancelInstall() ha d'anar ABANS de terminate"
