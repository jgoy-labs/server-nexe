"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/test_b3_nfkc_memory_ingest.py
Description: B3 NFKC symmetry — the memory-API ingest path must normalise text to
             NFKC so that fullwidth/halfwidth variants are indexed canonically.
             Behavioural test: exercises MemoryService.remember()/recall() for
             real, instead of statically grepping the source for the literal.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
import unicodedata

import pytest

from memory.memory.memory_service import MemoryService


@pytest.fixture
def svc(tmp_path):
    """MemoryService amb SQLite temporal i sense Qdrant (mateix patró que
    tests/memory/memory/test_memory_service.py)."""
    return MemoryService(db_path=tmp_path / "test.db", qdrant_path=None)


def _has_fullwidth(text: str) -> bool:
    """True si el text conté caràcters fullwidth/compat (no NFKC-canònics)."""
    return text != unicodedata.normalize("NFKC", text)


@pytest.mark.asyncio
async def test_memory_store_nfkc_fullwidth_to_halfwidth(svc):
    """remember() ha d'aplicar NFKC al text d'ingest.

    Es guarda text fullwidth i es comprova que el contingut emmagatzemat queda
    normalitzat a halfwidth (canònic), de manera que una consulta halfwidth el
    troba. Garanteix la simetria fullwidth indexat ↔ halfwidth consulta.
    """
    await svc.initialize()

    fullwidth = "My favourite city is Ｂａｒｃｅｌｏｎａ"
    assert _has_fullwidth(fullwidth), "el text de prova ha de ser fullwidth"

    entry_id = await svc.remember(user_id="u1", text=fullwidth, force=True)
    assert entry_id is not None

    # Consulta halfwidth → ha de trobar el text indexat fullwidth (post-NFKC).
    cards = await svc.recall(user_id="u1", query="favourite city")
    assert len(cards) >= 1

    # El contingut emmagatzemat ha de ser NFKC-canònic (sense fullwidth).
    matched = [c for c in cards if "Barcelona" in c.content]
    assert matched, "el contingut indexat no s'ha normalitzat a halfwidth (NFKC)"
    assert all(not _has_fullwidth(c.content) for c in matched)


@pytest.mark.asyncio
async def test_memory_store_nfkc_bidirectional(svc):
    """Simetria NFKC bidireccional ingest↔consulta (anti-regressió B3).

    Comprova el comportament real en les dues direccions:
      fullwidth indexat → consulta halfwidth → match
      halfwidth indexat → consulta fullwidth → match
    """
    await svc.initialize()

    # Direcció 1: indexat fullwidth, consulta halfwidth.
    await svc.remember(user_id="a", text="My favourite city is Ｂａｒｃｅｌｏｎａ", force=True)
    cards_a = await svc.recall(user_id="a", query="favourite city")
    assert any("Barcelona" in c.content for c in cards_a), (
        "ingest fullwidth no trobable amb consulta halfwidth (NFKC ingest perdut)"
    )

    # Direcció 2: indexat halfwidth, consulta fullwidth.
    await svc.remember(user_id="b", text="My favourite city is Barcelona", force=True)
    fullwidth_query = "favourite ｃｉｔｙ"
    assert _has_fullwidth(fullwidth_query), "la consulta de prova ha de ser fullwidth"
    cards_b = await svc.recall(user_id="b", query=fullwidth_query)
    assert any("Barcelona" in c.content for c in cards_b), (
        "consulta fullwidth no troba l'index halfwidth (NFKC consulta perdut)"
    )
