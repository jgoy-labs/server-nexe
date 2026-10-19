"""What the user stated about themselves reaches EVERY turn, with its date.

Live 13/10/2026: "Hola, Jordi" / "tens 45 anys" and, two turns later, «no tinc cap
font visible». The facts were in `personal_memory`; the question resembled none
of them and three documents filled the 3-5 hit limit (memory comes last).
"""
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.endpoints.chat_rag import _stated_on, build_rag_context
from core.rag.profile import PROFILE_MAX_FACTS, profile_hits

MEM = "personal_memory"


@pytest.fixture(autouse=True)
def _madrid(monkeypatch):
    """The day is the user's local one; pin it so the tests do not depend on the machine."""
    monkeypatch.setenv("TZ", "Europe/Madrid")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


def _point(text, created="2026-10-02T15:28:16.024490+00:00", type_="user_fact", pid=None):
    payload = {"text": text, "type": type_, "source": "web_ui"}
    if created:
        payload["created_at"] = created
    return SimpleNamespace(id=pid or text, payload=payload)


def _hit(text, collection, score=0.9, **meta):
    return SimpleNamespace(id=text, text=text, score=score, collection=collection, metadata=meta)


def _memory(points, search_hits=()):
    memory = MagicMock()
    memory.list_collections = AsyncMock(return_value=[])
    memory.collection_exists = AsyncMock(return_value=True)
    memory.embed_query = AsyncMock(return_value=[0.0])
    memory.scroll = AsyncMock(return_value=(list(points), None))
    memory.search = AsyncMock(return_value=list(search_hits))
    return memory


async def _context(memory, lang="ca", collections=None, **kw):
    with patch("memory.memory.api.v1.get_memory_api", AsyncMock(return_value=memory)):
        return await build_rag_context("com que no tens dades?", app_state=None, server_lang=lang,
                                       collections=collections, **kw)


# ── the date ────────────────────────────────────────────────────────────────

def test_the_date_comes_from_the_fact_in_each_language():
    meta = {"created_at": "2026-10-02T15:28:16+00:00"}
    assert _stated_on(meta, "ca") == " (t'ho va dir l'usuari el 02/10/2026)"
    assert _stated_on(meta, "es") == " (te lo dijo el usuario el 02/10/2026)"
    assert _stated_on(meta, "en") == " (the user told you on 2026-10-02)"


@pytest.mark.parametrize("meta", [{}, {"created_at": None}, {"created_at": "ahir"}, {"created_at": 5}])
def test_no_date_no_phrase_and_never_a_guess(meta):
    assert _stated_on(meta, "ca") == ""


# ── always there ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_facts_are_there_when_the_question_matches_none_of_them():
    memory = _memory([_point("L'usuari es diu Jordi"), _point("L'usuari té 45 anys")], search_hits=[])
    context, items = await _context(memory)
    assert "L'usuari es diu Jordi (t'ho va dir l'usuari el 02/10/2026)" in context
    assert "L'usuari té 45 anys (t'ho va dir l'usuari el 02/10/2026)" in context
    assert "web_ui" not in context and "[Font:" not in context
    assert items == [], "the badge counts what was searched, not what was always there"


@pytest.mark.asyncio
async def test_the_documents_cannot_push_the_facts_out_of_the_limit():
    docs = [_hit(f"document {i}", "user_knowledge") for i in range(6)]
    memory = _memory([_point("L'usuari es diu Jordi")], search_hits=docs)
    context, _ = await _context(memory, limit=3)
    assert "L'usuari es diu Jordi" in context
    assert context.count("document ") == 3


@pytest.mark.asyncio
async def test_a_fact_found_twice_is_said_once():
    fact = "L'usuari es diu Jordi"
    memory = _memory([_point(fact)], search_hits=[_hit(fact, MEM, created_at="2026-10-02T15:28:16+00:00")])
    context, _ = await _context(memory)
    assert context.count(fact) == 1


@pytest.mark.asyncio
async def test_memory_comes_before_the_documentation():
    memory = _memory([_point("L'usuari es diu Jordi")], search_hits=[_hit("doc", "nexe_documentation")])
    context, _ = await _context(memory)
    assert context.index("[MEMORIA DE L'USUARI]") < context.index("[DOCUMENTACIO DEL SISTEMA]")


@pytest.mark.asyncio
async def test_a_user_who_turned_memory_off_gets_no_personal_facts():
    memory = _memory([_point("L'usuari es diu Jordi")], search_hits=[])
    context, _ = await _context(memory, collections=["nexe_documentation"])
    assert "Jordi" not in context
    memory.scroll.assert_not_called()


@pytest.mark.asyncio
async def test_a_failing_list_costs_nothing_else():
    memory = _memory([], search_hits=[_hit("doc", "nexe_documentation")])
    memory.scroll = AsyncMock(side_effect=RuntimeError("qdrant down"))
    context, _ = await _context(memory)
    assert "doc" in context


# ── which facts, how many, in which order ───────────────────────────────────

@pytest.mark.asyncio
async def test_only_what_the_user_stated_is_listed():
    memory = _memory([_point("L'usuari es diu Jordi"), _point("El nom de test", type_="fact"),
                      _point("", type_="user_fact")])
    hits = await profile_hits(memory)
    assert [h.text for h in hits] == ["L'usuari es diu Jordi"]


@pytest.mark.asyncio
async def test_the_newest_come_first_and_there_is_a_ceiling():
    points = [_point(f"fet {i}", created=f"2026-09-{i + 1:02d}T10:00:00+00:00") for i in range(PROFILE_MAX_FACTS + 5)]
    hits = await profile_hits(_memory(points))
    assert len(hits) == PROFILE_MAX_FACTS
    assert hits[0].text == f"fet {PROFILE_MAX_FACTS + 4}" and hits[-1].text == "fet 5"


@pytest.mark.asyncio
async def test_no_collection_no_facts_no_error():
    memory = _memory([])
    memory.collection_exists = AsyncMock(return_value=False)
    assert await profile_hits(memory) == []
    memory.scroll.assert_not_called()


# ── what the review of 13/10 found ──────────────────────────────────────────

def test_the_day_is_the_local_one_not_the_utc_one():
    # 22:30 UTC on the 2nd is 00:30 on the 3rd in Madrid (CEST).
    assert _stated_on({"created_at": "2026-10-02T22:30:00+00:00"}, "ca") == " (t'ho va dir l'usuari el 03/10/2026)"


@pytest.mark.asyncio
async def test_a_dead_fact_is_not_listed_even_if_the_cleanup_is_late():
    dead = _point("L'usuari viu a Reus")
    dead.payload["expires_at"] = "2020-01-01T00:00:00+00:00"
    alive = _point("L'usuari es diu Jordi")
    alive.payload["expires_at"] = "2999-01-01T00:00:00+00:00"
    hits = await profile_hits(_memory([dead, alive]))
    assert [h.text for h in hits] == ["L'usuari es diu Jordi"]


@pytest.mark.asyncio
async def test_every_page_is_read_not_the_first_200():
    page1 = [_point(f"altre {i}", type_="fact") for i in range(200)]
    page2 = [_point("L'usuari es diu Jordi")]
    memory = _memory([])
    memory.scroll = AsyncMock(side_effect=[(page1, "next"), (page2, None)])
    hits = await profile_hits(memory)
    assert [h.text for h in hits] == ["L'usuari es diu Jordi"]
    assert memory.scroll.await_count == 2


@pytest.mark.asyncio
async def test_a_long_fact_is_cut_and_a_repeated_one_is_said_once():
    long_text = "x" * 1000
    hits = await profile_hits(_memory([_point(long_text), _point("L'usuari es diu Jordi", pid="a"),
                                       _point("L'usuari es diu Jordi", pid="b")]))
    assert sorted(len(h.text) for h in hits) == [21, 301]
    assert hits[0].text.endswith("…") or hits[1].text.endswith("…")
    assert [h.text for h in hits].count("L'usuari es diu Jordi") == 1
