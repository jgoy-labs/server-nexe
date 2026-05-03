"""Anti-regressió Cluster 11 — `code_chunker.py` regex match guards.

Cobreix els 2 findings mypy `union-attr` a
`memory/embeddings/chunkers/code_chunker.py:240` (`name = match_class.group(1)` en
una branca `else` precedida per `if match_func or match_class:`) i L309 (estructura
idèntica però amb 4 alternatives en JS: `is_func`, `is_export_func`, `is_class`,
`is_arrow`).

Mecànica: la disjunció garanteix runtime que dins l'`else` final, l'última
alternativa és truthy — però mypy no narrows en disjuncions múltiples i marca
`Item "None" of "Match[str] | None" has no attribute "group"`.

Decisió Director: Dev#2 fa refactor a `if/elif/else` explícit o afegeix `assert`
post-else. Runtime no canvia.

CONTRACTE PINAT (compatible amb qualsevol opció):
1. Donat un fitxer Python amb només una classe (sense funció), `_chunk_python`
   extreu correctament el nom de la classe via la branca `else` de L240.
2. Donat un fitxer Python amb només una funció, `_chunk_python` extreu el nom
   via la branca `if match_func`.
3. Donat un fitxer JS amb només una arrow function, `_chunk_javascript` extreu
   el nom via la branca `else` de L309.
4. Donat un fitxer JS amb només una `class`, `_chunk_javascript` extreu el nom
   via la branca `is_class`.

Pre-fix (HEAD `30eb2a6`): contracte runtime es compleix. Post-fix: ha de seguir
complint-se. Si Dev#2 simplifica/refactoritza la lògica `if/elif/else` i trenca
una branca, aquest test detecta la regressió.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def chunker():
    from memory.embeddings.chunkers.code_chunker import CodeChunker

    return CodeChunker()


def _python_class_only_source() -> str:
    """Fitxer Python amb només una classe (cap def top-level)."""
    return (
        "class OnlyClass:\n"
        "    \"\"\"Docstring.\"\"\"\n"
        "    attr = 1\n"
    )


def _python_function_only_source() -> str:
    """Fitxer Python amb només una funció (cap class top-level)."""
    return (
        "def only_function(x):\n"
        "    return x * 2\n"
    )


def test_chunk_python_class_only_extracts_name(chunker) -> None:
    """Cobreix la branca `else` de L240 (`name = match_class.group(1)`).

    Pre-fix: la branca s'executa amb `match_func=None, match_class=truthy` perquè
    la disjunció `if match_func or match_class:` ho garanteix. Post-fix:
    `if/elif` o `assert` mantenen el mateix output."""
    raw = chunker._chunk_python(_python_class_only_source())
    assert len(raw) == 1, f"Esperat 1 chunk, trobat {len(raw)}: {raw!r}"
    chunk_text, chunk_meta = raw[0]
    assert chunk_meta == {"name": "OnlyClass", "type": "class"}, (
        f"Metadata cluster 11 (class branch L240) trencada: {chunk_meta!r}."
    )
    assert "OnlyClass" in chunk_text


def test_chunk_python_function_only_extracts_name(chunker) -> None:
    """Cobreix la branca `if match_func` de L236-238.

    Aquest test té sentit junt amb el de class: assegura que les DUES branques
    funcionen, no només la del finding. Si Dev#2 refactoritza a `elif match_class`
    però es deixa el `match_func.group(2)` malament, aquest test salta."""
    raw = chunker._chunk_python(_python_function_only_source())
    assert len(raw) == 1
    _chunk_text, chunk_meta = raw[0]
    assert chunk_meta == {"name": "only_function", "type": "function"}


def test_chunk_javascript_arrow_only_extracts_name(chunker) -> None:
    """Cobreix la branca `else` de L309 (`name = is_arrow.group(3)`).

    Constructem un fitxer amb només una arrow function — `is_func`,
    `is_export_func`, `is_class` són tots None, i la branca `else` ha d'extreure
    el nom de la variable arrow."""
    js_source = (
        "const computeSum = (a, b) => {\n"
        "  return a + b;\n"
        "};\n"
    )
    raw = chunker._chunk_javascript(js_source)
    assert len(raw) == 1, f"Esperat 1 chunk, trobat {len(raw)}: {raw!r}"
    _chunk_text, chunk_meta = raw[0]
    assert chunk_meta == {"name": "computeSum", "type": "arrow_function"}, (
        f"Metadata cluster 11 (arrow branch L309) trencada: {chunk_meta!r}."
    )


def test_chunk_javascript_class_only_extracts_name(chunker) -> None:
    """Cobreix la branca `elif is_class` de L305-307. Co-test del cluster JS."""
    js_source = (
        "class Foo {\n"
        "  bar() { return 1; }\n"
        "}\n"
    )
    raw = chunker._chunk_javascript(js_source)
    assert len(raw) == 1
    _chunk_text, chunk_meta = raw[0]
    assert chunk_meta == {"name": "Foo", "type": "class"}


def test_chunk_javascript_function_only_extracts_name(chunker) -> None:
    """Cobreix la branca `if is_func` (primera) de L299-301."""
    js_source = (
        "function helper(arg) {\n"
        "  return arg + 1;\n"
        "}\n"
    )
    raw = chunker._chunk_javascript(js_source)
    assert len(raw) == 1
    _chunk_text, chunk_meta = raw[0]
    assert chunk_meta == {"name": "helper", "type": "function"}
