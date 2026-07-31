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

import re
from pathlib import Path

SWIFT_DIR = (
    Path(__file__).resolve().parent.parent
    / "installer" / "swift-wizard" / "Sources" / "InstallNexe"
)


# Qualsevol comparació on hi participi `ramGB`, en qualsevol dels dos ordres:
#   model.ramGB > usableRamGB        (op a la dreta de ramGB)
#   usableRamGB < model.ramGB        (op a l'esquerra, forma equivalent)
# Captura l'operador sencer perquè `>=` i `<=` no puguin passar com a `>` / `<`.
_RAM_COMPARISON_RE = re.compile(
    r"ramGB\s*(?P<after>>=|<=|>|<)"
    r"|(?P<before>>=|<=|>|<)\s*[\w.]*[rR]amGB"
)


def test_b171_model_picker_uses_strict_greater_than():
    """B171: un model a la frontera exacta (ramGB == 75% de la RAM) ha de ser
    SELECCIONABLE → la regla 'massa gran' ha de comparar amb operador estricte.

    Robust al refactor, a diferència de la versió original: aquella buscava una
    ÚNICA línia que contingués alhora `tooLarge`, `ramGB` i `0.75`, i va petar
    amb un `StopIteration` cec el dia que la decisió B va partir aquella línia
    en tres (el coeficient a `usableRamGB`, el test a `isTooLarge`, la crida al
    call-site) — cosa que era precisament el que calia fer.

    Ara la propietat s'expressa sense dependre de noms, de layout ni d'on visqui
    el 0.75: de TOTES les comparacions on intervé `ramGB` al fitxer, cap pot ser
    `>=` ni `<=`. Un `model.ramGB >= usableRamGB` — o el seu equivalent invertit
    `usableRamGB <= model.ramGB` — exclouria la frontera i deixaria un Mac de
    24 GB sense cap model seleccionable (mistral_small_24b demana exactament
    18.0 GB i el límit és exactament 18.0).
    """
    src = (SWIFT_DIR / "ModelPickerView.swift").read_text()
    ops = [
        m.group("after") or m.group("before")
        for m in _RAM_COMPARISON_RE.finditer(src)
    ]
    assert ops, (
        "B171: no trobo cap comparació sobre `ramGB` a ModelPickerView.swift — "
        "o el filtre de mida ha desaparegut, o ha canviat de fitxer"
    )
    inclusive = [op for op in ops if "=" in op]
    assert not inclusive, (
        f"B171: la regla de mida usa un operador inclusiu {inclusive} — "
        f"la frontera exacta deixa de ser seleccionable"
    )


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
