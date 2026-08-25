"""
────────────────────────────────────
Server Nexe — test
Author: Jordi Goy
Location: tests/memory/rag/test_g14_decorative_breakers.py
Description: #899 — un mòdul no pot DECLARAR un circuit breaker que ningú
             implementa. `memory/rag` declarava `circuit_breaker_threshold` i
             `circuit_breaker_timeout` (a `constants.py` i, duplicats, a
             `manifest.toml`) i cap línia de codi els llegia: `get_info()` els
             publicava a la resposta del mòdul, o sigui que el producte deia
             tenir una protecció que no existeix. Precedent: el `qdrant_breaker`
             es va retirar per la mateixa raó (WS7-01), i la regla A10 gate 2 ho
             prohibeix.

             Aquest gate NO enumera els dos fitxers del defecte: DESCOBREIX tots
             els `manifest.toml` / `constants.py` de producció, i per a cada
             declaració amb pinta de breaker exigeix que el mòdul que la fa
             importi la implementació real (`core.resilience`). Si algú el
             reintrodueix en un altre mòdul, també cau.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

# Directoris que no són codi de producció d'aquest repo.
_SKIP = ("venv", ".venv", ".test_venv", "worktrees", "node_modules", ".git",
         "tests", "dev-tools", "__pycache__", "docs", "storage")

# La ÚNICA implementació de circuit breaker del repo. Un mòdul que declara
# paràmetres de breaker i no la importa, declara una protecció que no té.
_REAL_BREAKER = "core.resilience"

_KEY_RE = re.compile(r'^\s*[\'"]?([A-Za-z0-9_.]*breaker[A-Za-z0-9_.]*)[\'"]?\s*[:=]', re.I)
_SECTION_RE = re.compile(r'^\s*\[([^\]]*breaker[^\]]*)\]', re.I)

# Control d'abast (§1.7): si la descoberta es trenca (un canvi de layout, un
# filtre massa ample), el gate deixaria de mirar sense dir res. Aquests mínims
# són els mesurats avui; si baixen, és que el gate ha deixat de veure el repo.
_MIN_DECL_FILES = 20


def _declaration_files() -> list[Path]:
    """Tots els fitxers de declaració de mòdul del repo (descoberta)."""
    out = []
    for pattern in ("**/manifest.toml", "**/constants.py"):
        for p in ROOT.glob(pattern):
            if any(part in _SKIP for part in p.relative_to(ROOT).parts):
                continue
            out.append(p)
    return sorted(out)


def _module_dir(decl: Path) -> Path:
    """El mòdul propietari de la declaració: el directori on viu."""
    return decl.parent


def _module_imports_real_breaker(module_dir: Path) -> bool:
    for py in module_dir.rglob("*.py"):
        if "__pycache__" in py.parts:
            continue
        if _REAL_BREAKER in py.read_text(encoding="utf-8", errors="ignore"):
            return True
    return False


def _breaker_declarations(decl: Path) -> list[tuple[int, str]]:
    hits = []
    for i, line in enumerate(decl.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
        if line.lstrip().startswith("#"):
            continue
        m = _KEY_RE.match(line) or _SECTION_RE.match(line)
        if m:
            hits.append((i, m.group(1)))
    return hits


class TestG14NoDecorativeBreakers:

    def test_the_scan_still_sees_the_repo(self):
        """Control d'abast: la descoberta ha de seguir trobant les declaracions."""
        found = _declaration_files()
        assert len(found) >= _MIN_DECL_FILES, (
            f"la descoberta només veu {len(found)} fitxers de declaració (mínim "
            f"registrat {_MIN_DECL_FILES}): el gate ha deixat de mirar el repo"
        )

    def test_no_module_declares_a_breaker_it_does_not_implement(self):
        """#899: declarar protecció sense codi que l'executi és observabilitat falsa."""
        offenders = []
        for decl in _declaration_files():
            hits = _breaker_declarations(decl)
            if not hits:
                continue
            if _module_imports_real_breaker(_module_dir(decl)):
                continue
            rel = decl.relative_to(ROOT)
            offenders += [f"{rel}:{ln} → {key}" for ln, key in hits]

        assert not offenders, (
            "#899: declaracions de circuit breaker sense implementació que les "
            "llegeixi (regla A10 gate 2 — el mòdul ni tan sols importa "
            f"`{_REAL_BREAKER}`):\n  " + "\n  ".join(offenders)
        )
