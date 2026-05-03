"""Anti-regressió cluster `folder` ingest_knowledge (Onada 4.1, BUS Dev#1bis).

Cobreix els findings mypy #31, #37, #40 (`01-classificacio.md`). Pina el
contracte de signatura: `ingest_knowledge(folder=None, ...)` ha de continuar
acceptant None com a default value (per usar el fallback PROJECT_ROOT/knowledge
documentat al docstring de la funció).

El fix Dev#2 canviarà l'anotació `folder: Path = None` per
`folder: Optional[Path] = None`. El default value (None) *no canvia*; només
l'anotació estàtica. Aquest test pina el contracte runtime: pre-fix passa
(default ja és None) i post-fix continua passant.

CEC: només firma. NO s'executa el cos de la funció (la coroutine es crea i
es tanca sense awaitar).
"""

from __future__ import annotations

import asyncio
import inspect


def test_ingest_knowledge_folder_default_is_none() -> None:
    """Pina contracte signatura: `folder` default = None."""
    from core.ingest.ingest_knowledge import ingest_knowledge

    sig = inspect.signature(ingest_knowledge)
    assert "folder" in sig.parameters, (
        "ingest_knowledge ha perdut el paràmetre `folder` — trenca cluster #31."
    )
    folder_param = sig.parameters["folder"]
    assert folder_param.default is None, (
        f"ingest_knowledge.folder.default = {folder_param.default!r}, esperat None. "
        "El fix Onada 4.1 ha de mantenir el default a None i només canviar "
        "l'anotació a Optional[Path]."
    )


def test_ingest_knowledge_accepts_explicit_none() -> None:
    """Pina contracte de crida: `ingest_knowledge(folder=None)` no llança
    TypeError de binding (cf. scripts/bench_ingest_bug16.py:107 #40 i
    `core/ingest/ingest_knowledge.py:562` #37 que passen folder=None).

    CEC: la coroutine es tanca sense executar el cos.
    """
    from core.ingest.ingest_knowledge import ingest_knowledge

    sig = inspect.signature(ingest_knowledge)
    bound = sig.bind(folder=None)
    bound.apply_defaults()
    assert bound.arguments["folder"] is None
    assert bound.arguments["quiet"] is False

    coro = ingest_knowledge(folder=None)
    try:
        assert asyncio.iscoroutine(coro)
    finally:
        coro.close()
