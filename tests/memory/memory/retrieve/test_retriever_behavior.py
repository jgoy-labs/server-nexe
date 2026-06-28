"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/memory/memory/retrieve/test_retriever_behavior.py
Description: MC-065 — behavioral tests for Retriever with fake stores and
    embedder: critical cards always survive the token budget (an allergy can
    never be dropped from context), dynamic threshold fallback + floor/ceiling
    clamps, exploratory mode forcing base_threshold, re-rank bonuses and
    ordering, and critical profile retrieval on non-matching queries.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from pathlib import Path

import pytest

from memory.memory.config import MemoryConfig
from memory.memory.models.memory_entry import MemoryCard
from memory.memory.retrieve.retriever import Retriever
from memory.memory.storage.sqlite_store import SQLiteStore

USER = "retrieve-user"
SESSION = "session-1"

# Default config: total budget = min(800, int(4096 * 0.10)) = 409 tokens
DEFAULT_BUDGET = 409


class FakeEmbedder:
    """Deterministic embedder double (no model download)."""

    def encode(self, text: str):
        return [0.1, 0.2, 0.3]


class FakeVectorIndex:
    """VectorIndex double returning canned candidates."""

    available = True

    def __init__(self, candidates):
        self._candidates = candidates
        self.search_calls = []

    def search(self, embedding, user_id, threshold, limit, namespace=None):
        self.search_calls.append(
            {"user_id": user_id, "threshold": threshold, "limit": limit,
             "namespace": namespace}
        )
        return list(self._candidates)


def _card(content, source_store="episodic", score=0.5, critical=False, entry_id=None):
    return MemoryCard(
        content=content,
        source_store=source_store,
        score=score,
        entry_id=entry_id,
        metadata={"is_critical": True} if critical else {},
    )


def _words(n: int) -> str:
    return " ".join(f"w{i}" for i in range(n))


@pytest.fixture
def retriever() -> Retriever:
    return Retriever(config=MemoryConfig())


@pytest.fixture
def store(tmp_path: Path) -> SQLiteStore:
    s = SQLiteStore(tmp_path / "retrieve_behavior.db")
    yield s
    s.close()


class TestApplyBudget:
    """(1) critical cards are ALWAYS included; normals dropped when over budget."""

    def test_critical_included_even_when_over_budget(self, retriever):
        # Critical card alone already exceeds the 409-token budget.
        critical = _card(_words(DEFAULT_BUDGET + 91), critical=True, entry_id="crit")
        normal = _card(_words(5), entry_id="norm")
        selected = retriever._apply_budget([critical, normal])
        ids = [c.entry_id for c in selected]
        assert "crit" in ids  # regression: an allergy can never be dropped
        assert "norm" not in ids  # remaining budget is 0 -> normal discarded

    def test_normals_fill_remaining_budget_in_order(self, retriever):
        a = _card(_words(300), entry_id="a", score=0.9)
        b = _card(_words(100), entry_id="b", score=0.8)
        c = _card(_words(50), entry_id="c", score=0.7)
        # 300 fits (remaining 109), 100 fits (remaining 9), 50 does not.
        selected = retriever._apply_budget([a, b, c])
        assert [card.entry_id for card in selected] == ["a", "b"]

    def test_critical_selected_before_normals_regardless_of_input_order(self, retriever):
        big_normal = _card(_words(400), entry_id="big")
        critical = _card(_words(10), critical=True, entry_id="crit")
        selected = retriever._apply_budget([big_normal, critical])
        # Critical reserved first: 409 - 10 = 399 < 400 -> big normal dropped.
        assert [card.entry_id for card in selected] == ["crit"]

    def test_everything_fits_nothing_dropped(self, retriever):
        cards = [_card(_words(20), entry_id=f"n{i}") for i in range(5)]
        cards.append(_card(_words(20), critical=True, entry_id="crit"))
        selected = retriever._apply_budget(cards)
        assert len(selected) == 6


class TestDynamicThreshold:
    """(2) fallback under 3 candidates; floor/ceiling clamps with many."""

    def test_fewer_than_three_candidates_falls_back(self, retriever):
        fallback = retriever._config.retrieve.fallback_threshold  # 0.55
        assert retriever._dynamic_threshold([]) == fallback
        assert retriever._dynamic_threshold([{"score": 0.9}]) == fallback
        assert retriever._dynamic_threshold([{"score": 0.9}, {"score": 0.2}]) == fallback

    def test_high_scores_clamped_to_ceiling(self, retriever):
        candidates = [{"score": 0.9} for _ in range(5)]
        # median 0.9, std 0 -> dynamic 0.9 -> clamped to ceiling 0.65
        assert retriever._dynamic_threshold(candidates) == pytest.approx(0.65)

    def test_low_scores_clamped_to_floor(self, retriever):
        candidates = [{"score": 0.40}, {"score": 0.41}, {"score": 0.42}]
        # median 0.41, std ~0.01 -> dynamic ~0.415 -> clamped to floor 0.45
        assert retriever._dynamic_threshold(candidates) == pytest.approx(0.45)

    def test_mid_scores_pass_through_unclamped(self, retriever):
        candidates = [{"score": 0.5} for _ in range(4)]
        # median 0.5, std 0 -> dynamic 0.5, inside [0.45, 0.65]
        assert retriever._dynamic_threshold(candidates) == pytest.approx(0.5)


class TestExploratoryMode:
    """(3) mode='exploratory' forces base_threshold instead of the dynamic one."""

    CANDIDATES = [
        {"id": f"c{i}", "score": s, "payload": {"content": f"candidate {i}"}}
        for i, s in enumerate([0.41, 0.60, 0.62, 0.64])
    ]
    # Dynamic threshold: median 0.61 + 0.5*std(~0.106) ~= 0.663 -> ceiling 0.65.
    # All candidate scores are below 0.65, so normal mode keeps NOTHING,
    # while exploratory mode (base_threshold 0.40) keeps all four.

    def _retriever(self):
        return Retriever(
            config=MemoryConfig(),
            vector_index=FakeVectorIndex(self.CANDIDATES),
            embedder=FakeEmbedder(),
        )

    def test_normal_mode_uses_dynamic_threshold(self):
        cards = self._retriever()._retrieve_vector(USER, "query", None, mode="normal")
        assert cards == []

    def test_exploratory_mode_forces_base_threshold(self):
        cards = self._retriever()._retrieve_vector(
            USER, "query", None, mode="exploratory"
        )
        assert len(cards) == 4
        assert {c.source_store for c in cards} == {"episodic"}
        assert {c.entry_id for c in cards} == {"c0", "c1", "c2", "c3"}


class TestRerank:
    """(4) re-rank applies the right bonuses and sorts by score descending."""

    def test_bonuses_and_ordering(self, retriever):
        working = _card("from working", source_store="working", score=0.50,
                        entry_id="working")
        profile = _card("from profile", source_store="profile", score=0.58,
                        entry_id="profile")
        critical = _card("critical episodic", source_store="episodic", score=0.56,
                         critical=True, entry_id="critical")
        plain = _card("plain episodic", source_store="episodic", score=0.62,
                      entry_id="plain")

        ranked = retriever._rerank([working, profile, critical, plain])

        scores = {c.entry_id: c.score for c in ranked}
        assert scores["working"] == pytest.approx(0.60)   # +0.1 working bonus
        assert scores["profile"] == pytest.approx(0.63)   # +0.05 profile bonus
        assert scores["critical"] == pytest.approx(0.66)  # +0.1 critical bonus
        assert scores["plain"] == pytest.approx(0.62)     # no bonus
        assert [c.entry_id for c in ranked] == [
            "critical", "profile", "plain", "working",
        ]

    def test_score_capped_at_one(self, retriever):
        stacked = _card("profile + critical", source_store="profile", score=0.95,
                        critical=True, entry_id="stacked")
        ranked = retriever._rerank([stacked])
        assert ranked[0].score == 1.0


class TestRetrieveProfile:
    """(5) critical profile cards returned even when the query does not match."""

    def test_critical_included_on_unrelated_query(self, store):
        store.upsert_profile(
            USER, "allergy", "peanuts", trust_level="trusted", is_critical=True
        )
        store.upsert_profile(USER, "favorite_color", "blue", is_critical=False)
        retriever = Retriever(config=MemoryConfig(), sqlite_store=store)

        cards = retriever._retrieve_profile(USER, "weather forecast tomorrow")

        assert len(cards) == 1
        card = cards[0]
        assert "allergy" in card.content
        assert card.metadata.get("is_critical")
        assert card.score == pytest.approx(0.9)
        assert card.confidence == "high"  # trusted -> high

    def test_relevant_non_critical_included_with_lower_score(self, store):
        store.upsert_profile(
            USER, "allergy", "peanuts", trust_level="trusted", is_critical=True
        )
        store.upsert_profile(USER, "favorite_color", "blue", is_critical=False)
        retriever = Retriever(config=MemoryConfig(), sqlite_store=store)

        cards = retriever._retrieve_profile(USER, "show me blue things")

        by_attr = {c.content.split(":")[0]: c for c in cards}
        assert set(by_attr) == {"allergy", "favorite_color"}
        color = by_attr["favorite_color"]
        assert color.score == pytest.approx(0.7)
        assert color.confidence == "moderate"  # untrusted -> moderate
        assert not color.metadata.get("is_critical")


class TestRetrieveEndToEnd:
    """retrieve(): the critical allergy survives even when a huge episodic
    candidate would otherwise eat the whole token budget."""

    def test_critical_profile_survives_budget_pressure(self, store):
        store.upsert_profile(
            USER, "allergy", "peanuts", trust_level="trusted", is_critical=True
        )
        # The huge episodic must exist in SQLite so it is hydrated and then
        # genuinely dropped by the token budget (not by the hydration filter).
        huge_id = store.insert_episodic(USER, _words(450))  # 450 tokens > 409 budget
        huge = {
            "id": huge_id,
            "score": 0.9,
            "payload": {"rdbms_id": huge_id},  # real VectorIndex stores no content
        }
        retriever = Retriever(
            config=MemoryConfig(),
            sqlite_store=store,
            vector_index=FakeVectorIndex([huge]),
            embedder=FakeEmbedder(),
        )

        cards = retriever.retrieve(USER, SESSION, "anything to eat tonight?")

        ids = [c.entry_id for c in cards]
        assert huge_id not in ids  # over budget -> dropped
        assert any(
            c.source_store == "profile" and c.metadata.get("is_critical")
            for c in cards
        )


class TestRetrieveVectorHydration:
    """B112: vector hits hydrate real content from SQLite (the Qdrant payload
    stores metadata only), and ids absent from SQLite are dropped (no leak)."""

    def test_hydrates_content_from_sqlite(self, store):
        eid = store.insert_episodic(USER, "I love climbing in the Pyrenees")
        cand = {"id": eid, "score": 0.9, "payload": {"rdbms_id": eid}}  # no content
        retriever = Retriever(
            config=MemoryConfig(),
            sqlite_store=store,
            vector_index=FakeVectorIndex([cand]),
            embedder=FakeEmbedder(),
        )

        cards = retriever._retrieve_vector(USER, "mountains", None, "exploratory")

        assert len(cards) == 1
        assert cards[0].content == "I love climbing in the Pyrenees"
        assert not cards[0].content.startswith("[episodic:")

    def test_drops_ids_absent_from_sqlite(self, store):
        cand = {"id": "ghost", "score": 0.9, "payload": {"rdbms_id": "ghost"}}
        retriever = Retriever(
            config=MemoryConfig(),
            sqlite_store=store,
            vector_index=FakeVectorIndex([cand]),
            embedder=FakeEmbedder(),
        )

        cards = retriever._retrieve_vector(USER, "x", None, "exploratory")

        assert cards == []
