"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/test_b3_nfkc_memory_ingest.py
Description: TDD cec — B3 NFKC asimetria: path ingest memory-API no normalitza
             text a NFKC. El commit 3469964 va arreglar la query però no l'ingest
             via MemoryService.remember(). Fix: afegir NFKC a remember() (Opció b).
             Onada 4.6b / xfail strict pre-fix.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
from pathlib import Path

import pytest

_MEMORY_SERVICE_FILE = Path(__file__).parents[1] / "memory" / "memory" / "memory_service.py"
_MEMORY_API_V1_FILE = Path(__file__).parents[1] / "memory" / "memory" / "api" / "v1.py"


def _remember_fn_src() -> str:
    src = _MEMORY_SERVICE_FILE.read_text()
    fn_start = src.find("async def remember(")
    if fn_start < 0:
        fn_start = src.find("def remember(")
    next_fn = src.find("\n    async def ", fn_start + 1)
    if next_fn < 0:
        next_fn = src.find("\n    def ", fn_start + 1)
    return src[fn_start:next_fn] if next_fn > fn_start > 0 else src[fn_start:]


def _has_nfkc(src: str) -> bool:
    return (
        'unicodedata.normalize("NFKC"' in src
        or "unicodedata.normalize('NFKC'" in src
    )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "B3: MemoryService.remember() no aplica NFKC al text — asimetria amb query path. "
        "Commit 3469964 va arreglar query, NO ingest memory-API. "
        "Fix: afegir NFKC a remember() (additiu, Opció b Director). (Onada 4.6b, pre-fix)"
    ),
)
def test_memory_store_nfkc_fullwidth_to_halfwidth():
    """MemoryService.remember() ha d'aplicar NFKC al text d'ingest.

    Post-fix: unicodedata.normalize("NFKC", text) ha d'aparèixer a remember()
    abans de passar el text als embedders/extractor.
    Garanteix simetria: fullwidth indexat ↔ halfwidth query i viceversa.
    """
    remember_src = _remember_fn_src()
    assert _has_nfkc(remember_src), (
        "B3: MemoryService.remember() ha d'aplicar unicodedata.normalize('NFKC', text) "
        "al text d'ingest (fix additiu — NO treure NFKC del query path)"
    )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "B3 anti-reg: ingest path sense NFKC — simetria bidireccional no garantida fins post-fix. "
        "Guard estructural: query path (commit 3469964) + ingest path (fix B3) han de tenir NFKC. "
        "(Onada 4.6b, pre-fix)"
    ),
)
def test_memory_store_nfkc_bidirectional():
    """Anti-regressió B3: simetria NFKC bidireccional ingest↔query.

    Verifica que TANT el path d'ingest (MemoryService.remember) COM el path
    de query (memory/api/v1.py) apliquen NFKC, garantint:
      fullwidth indexat → halfwidth query → match
      halfwidth indexat → fullwidth query → match
    Dev#2 treu el xfail quan el fix és aplicat. Queda com a guard permanent.
    """
    remember_src = _remember_fn_src()
    api_src = _MEMORY_API_V1_FILE.read_text()

    # Query path (commit 3469964 — ja existent, no ha de regredir)
    assert _has_nfkc(api_src), (
        "Anti-reg query path (commit 3469964): memory/api/v1.py ha perdut NFKC "
        "(regressió)"
    )

    # Ingest path (post-fix B3 — ha d'existir al remember())
    assert _has_nfkc(remember_src), (
        "Anti-reg ingest path B3: MemoryService.remember() ha de mantenir NFKC "
        "— simetria bidireccional indexat↔query"
    )
