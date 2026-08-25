"""
────────────────────────────────────
Server Nexe — test
Author: Jordi Goy
Location: tests/memory/memory/api/test_g17_text_store_retired.py
Description: #907 — el `TextStore` mai va arribar a néixer. `MemoryAPI` el
             creava només si rebia `text_store_path`, que per defecte és `None`
             i que CAP dels sis cridadors reals passa mai; `self._text_store`
             era per tant sempre `None` i totes les branques `if text_store:`
             de `documents.py` eren codi que no s'executa. `delete_collection()`
             no tenia ni cridador. Decisió de Jordi: esborrar-lo i deixar la
             traça al registre de magatzems.

             Gate per DESCOBERTA (§1.7), no per llista: recorre el codi de
             producte amb AST i falla si l'identificador torna a aparèixer en
             QUALSEVOL fitxer — paràmetre, atribut, import o crida. Mira codi,
             no text: els comentaris de paritat de `core/crypto/provider.py` i
             `memory/memory/storage/sqlite_store.py` citen `text_store.py` com a
             referència històrica i no són codi mort (ni són d'aquesta fitxa).

             Mutació que l'ha de matar: reintroduir un `if text_store:` a
             qualsevol fitxer de producció → vermell amb fitxer:línia.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]

# Allowlist dels directoris de producte (la mateixa idea que el gate d'SSL de
# #865: una denylist de caches sempre acaba tenint un forat).
PRODUCT_DIRS = ("core", "memory", "plugins", "personality", "installer", "scripts")

# Si l'escaneig deixa de veure el repo, el gate passaria per no mirar res.
_MIN_FILES = 200

_NEEDLES = ("text_store", "textstore")


def _product_files() -> list[Path]:
    out = []
    for d in PRODUCT_DIRS:
        base = ROOT / d
        if not base.is_dir():
            continue
        out += [p for p in base.rglob("*.py") if "__pycache__" not in p.parts]
    return sorted(out)


def _identifier_hits(path: Path) -> list[str]:
    """Aparicions de l'identificador EN CODI (no en comentaris ni docstrings)."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
    except SyntaxError:  # pragma: no cover - un .py il·legible no és feina d'aquest gate
        return []
    hits = []
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Name):
            names = [node.id]
        elif isinstance(node, ast.Attribute):
            names = [node.attr]
        elif isinstance(node, ast.arg):
            names = [node.arg]
        elif isinstance(node, ast.keyword) and node.arg:
            names = [node.arg]
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names = [node.name]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""] + [a.name for a in node.names]
        elif isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        for n in names:
            if any(needle in n.lower() for needle in _NEEDLES):
                hits.append(f"{path.relative_to(ROOT)}:{getattr(node, 'lineno', '?')} → {n}")
    return hits


class TestG17TextStoreIsGone:

    def test_the_scan_still_sees_the_product(self):
        """Control d'abast: sense això, un gate que no mira res sempre és verd."""
        n = len(_product_files())
        assert n >= _MIN_FILES, (
            f"l'escaneig només veu {n} fitxers de producció (mínim registrat "
            f"{_MIN_FILES}): ha deixat de mirar el repo"
        )

    def test_no_production_code_mentions_the_text_store(self):
        """#907: cap paràmetre, atribut, import ni crida en tot el producte."""
        offenders: list[str] = []
        for path in _product_files():
            offenders += _identifier_hits(path)

        assert not offenders, (
            "#907: el TextStore ha tornat al codi de producció (era un magatzem "
            "que no es va instanciar mai, cap cridador li passava el path):\n  "
            + "\n  ".join(offenders)
        )

    def test_the_module_file_is_gone(self):
        assert not (ROOT / "memory" / "memory" / "api" / "text_store.py").exists(), (
            "#907: memory/memory/api/text_store.py ha tornat"
        )
