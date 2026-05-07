"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/test_b3_nfkc_memory_ingest.py
Description: Blind TDD — B3 NFKC asymmetry: memory-API ingest path does not normalise
             text to NFKC. Commit 3469964 fixed the query but not the ingest
             via MemoryService.remember(). Fix: add NFKC to remember() (Option b).
             Wave 4.6b / xfail strict pre-fix.

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


def test_memory_store_nfkc_fullwidth_to_halfwidth():
    """MemoryService.remember() must apply NFKC to the ingest text.

    Post-fix: unicodedata.normalize("NFKC", text) must appear in remember()
    before passing the text to embedders/extractor.
    Guarantees symmetry: fullwidth indexed ↔ halfwidth query and vice versa.
    """
    remember_src = _remember_fn_src()
    assert _has_nfkc(remember_src), (
        "B3: MemoryService.remember() ha d'aplicar unicodedata.normalize('NFKC', text) "
        "al text d'ingest (fix additiu — NO treure NFKC del query path)"
    )


def test_memory_store_nfkc_bidirectional():
    """Anti-regression B3: bidirectional NFKC symmetry ingest↔query.

    Verifies that BOTH the ingest path (MemoryService.remember) AND the query
    path (memory/api/v1.py) apply NFKC, guaranteeing:
      fullwidth indexed → halfwidth query → match
      halfwidth indexed → fullwidth query → match
    Dev#2 removes the xfail once the fix is applied. Remains as a permanent guard.
    """
    remember_src = _remember_fn_src()
    api_src = _MEMORY_API_V1_FILE.read_text()

    # Query path (commit 3469964 — already present, must not regress)
    assert _has_nfkc(api_src), (
        "Anti-reg query path (commit 3469964): memory/api/v1.py ha perdut NFKC "
        "(regressió)"
    )

    # Ingest path (post-fix B3 — must exist in remember())
    assert _has_nfkc(remember_src), (
        "Anti-reg ingest path B3: MemoryService.remember() ha de mantenir NFKC "
        "— simetria bidireccional indexat↔query"
    )
