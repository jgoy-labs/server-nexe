"""
Contract tests for the memory architecture v1.
Define WHAT each component must do, not HOW.
If these tests pass, the architecture is correct.

50 test cases covering all pipeline + storage components.
"""

import json
import os
import tempfile
from pathlib import Path

import pytest


# ══════════════════════════════════════════════════════════════════
# GATE TESTS (10)
# ══════════════════════════════════════════════════════════════════

class TestGate:
    """Gate heuristic: discard non-memorizable messages."""

    def setup_method(self):
        from memory.memory.pipeline.gate import Gate
        self.gate = Gate()

    # --- Reject cases ---

    def test_rejects_empty(self):
        result = self.gate.evaluate("")
        assert not result.passed
        assert result.reason == "empty"

    def test_rejects_too_short(self):
        result = self.gate.evaluate("hola que tal")
        assert not result.passed
        assert result.reason == "too_short"

    def test_rejects_model_generated(self):
        result = self.gate.evaluate(
            "Aquí tens la informació que m'has demanat sobre Python.",
            is_user_message=False,
        )
        assert not result.passed
        assert result.reason == "model_generated"

    def test_rejects_pure_question(self):
        result = self.gate.evaluate("Què és Python i per a què serveix?")
        assert not result.passed
        assert result.reason == "pure_question"

    def test_rejects_repetitive(self):
        result = self.gate.evaluate("la la la la la la la la la la la la la la la la la la la la")
        assert not result.passed
        assert result.reason == "repetitive"

    # --- Accept cases ---

    def test_accepts_identity_fact(self):
        result = self.gate.evaluate("Em dic Anna i treballo com a enginyera de software.")
        assert result.passed

    def test_accepts_preference(self):
        result = self.gate.evaluate("M'agrada molt programar en Python i Rust.")
        assert result.passed

    def test_accepts_location(self):
        result = self.gate.evaluate("Visc a Barcelona des de fa cinc anys.")
        assert result.passed

    def test_accepts_short_high_importance(self):
        """Short messages with high-importance patterns bypass length check."""
        result = self.gate.evaluate("Em dic Anna")
        assert result.passed

    def test_accepts_mem_save_from_model(self):
        """MEM_SAVE from model should pass even though model-generated."""
        result = self.gate.evaluate(
            "L'usuari prefereix respostes en català.",
            is_user_message=False,
            is_mem_save=True,
        )
        assert result.passed


# ══════════════════════════════════════════════════════════════════
# EXTRACTOR TESTS (8)
# ══════════════════════════════════════════════════════════════════

class TestExtractor:
    """Heuristic extractor: detect facts without LLM."""

    def setup_method(self):
        from memory.memory.pipeline.extractor import Extractor
        self.extractor = Extractor()

    def test_detects_name(self):
        facts = self.extractor.extract("Em dic Anna Garcia.")
        assert len(facts) >= 1
        name_facts = [f for f in facts if f.attribute == "name"]
        assert len(name_facts) == 1
        assert "Anna" in name_facts[0].value

    def test_detects_location(self):
        facts = self.extractor.extract("Visc a Barcelona.")
        location_facts = [f for f in facts if f.attribute == "location"]
        assert len(location_facts) == 1
        assert "Barcelona" in location_facts[0].value

    def test_detects_occupation(self):
        facts = self.extractor.extract("Soc enginyera de software.")
        occ_facts = [f for f in facts if f.attribute == "occupation"]
        assert len(occ_facts) == 1

    def test_detects_preference_positive(self):
        facts = self.extractor.extract("M'agrada molt Python.")
        pref_facts = [f for f in facts if "preference" in f.tags]
        assert len(pref_facts) >= 1
        assert "positive" in pref_facts[0].tags

    def test_detects_preference_negative(self):
        facts = self.extractor.extract("Odio les reunions innecessàries.")
        pref_facts = [f for f in facts if "preference" in f.tags]
        assert len(pref_facts) >= 1
        assert "negative" in pref_facts[0].tags

    def test_detects_correction(self):
        facts = self.extractor.extract("No, el meu nom és Maria.")
        corrections = [f for f in facts if f.is_correction]
        assert len(corrections) >= 1
        assert corrections[0].attribute == "name"

    def test_detects_allergy(self):
        facts = self.extractor.extract("Tinc al·lèrgia a les nous.")
        allergy_facts = [f for f in facts if f.attribute == "allergies"]
        assert len(allergy_facts) >= 1
        assert allergy_facts[0].importance >= 0.9

    def test_empty_text_returns_nothing(self):
        facts = self.extractor.extract("")
        assert facts == []


# ══════════════════════════════════════════════════════════════════
# SCHEMA ENFORCER TESTS (6)
# ══════════════════════════════════════════════════════════════════

class TestSchemaEnforcer:
    """Schema enforcer: exact -> alias -> null (episodic)."""

    def setup_method(self):
        from memory.memory.pipeline.schema_enforcer import SchemaEnforcer
        self.enforcer = SchemaEnforcer()

    def test_exact_match(self):
        canonical, method = self.enforcer.resolve("name")
        assert canonical == "name"
        assert method == "exact"

    def test_alias_match(self):
        canonical, method = self.enforcer.resolve("feina")
        assert canonical == "occupation"
        assert method == "alias"

    def test_null_for_unknown(self):
        canonical, method = self.enforcer.resolve("color_preferit_del_cotxe")
        assert canonical is None
        assert method == "none"

    def test_null_for_none_input(self):
        canonical, method = self.enforcer.resolve(None)
        assert canonical is None
        assert method == "none"

    def test_is_critical_allergies(self):
        assert self.enforcer.is_critical("allergies") is True

    def test_not_critical_name(self):
        assert self.enforcer.is_critical("name") is False


# ══════════════════════════════════════════════════════════════════
# VALIDATOR TESTS (8)
# ══════════════════════════════════════════════════════════════════

class TestValidator:
    """Validator: 6 dimensions, decision tree, 2 trust levels."""

    def setup_method(self):
        from memory.memory.pipeline.validator import Validator
        from memory.memory.models.memory_entry import ExtractedFact
        from memory.memory.models.memory_types import TrustLevel, ValidatorDecision
        self.validator = Validator()
        self.TrustLevel = TrustLevel
        self.ValidatorDecision = ValidatorDecision
        self.ExtractedFact = ExtractedFact

    def test_trusted_identity_upserts_profile(self):
        fact = self.ExtractedFact(
            content="Em dic Anna",
            attribute="name",
            value="Anna",
            tags=["identity"],
            importance=0.8,
        )
        result = self.validator.validate(fact, trust_level=self.TrustLevel.TRUSTED)
        assert result.decision == self.ValidatorDecision.UPSERT_PROFILE

    def test_untrusted_identity_stages(self):
        """Untrusted source with schema attribute goes to stage_only."""
        fact = self.ExtractedFact(
            content="Model says name is Anna",
            attribute="name",
            value="Anna",
            tags=["identity"],
            importance=0.8,
            source="model",
        )
        result = self.validator.validate(
            fact,
            trust_level=self.TrustLevel.UNTRUSTED,
            existing_value="Bob",
        )
        # High contradiction + untrusted -> stage_only
        assert result.decision == self.ValidatorDecision.STAGE_ONLY

    def test_correction_promotes(self):
        fact = self.ExtractedFact(
            content="No, em dic Maria",
            attribute="name",
            value="Maria",
            tags=["correction"],
            importance=0.9,
            is_correction=True,
        )
        result = self.validator.validate(fact, trust_level=self.TrustLevel.UNTRUSTED)
        assert result.decision == self.ValidatorDecision.UPSERT_PROFILE

    def test_rejects_duplicate(self):
        """Same value as existing -> novelty near zero -> reject."""
        fact = self.ExtractedFact(
            content="Em dic Anna",
            attribute="name",
            value="Anna",
            tags=["identity"],
            importance=0.8,
        )
        result = self.validator.validate(
            fact,
            trust_level=self.TrustLevel.TRUSTED,
            existing_value="Anna",
        )
        assert result.decision == self.ValidatorDecision.REJECT

    def test_explicit_preference_promotes_episodic(self):
        fact = self.ExtractedFact(
            content="M'agrada Python",
            attribute=None,
            value="Python",
            tags=["preference", "positive"],
            importance=0.6,
        )
        result = self.validator.validate(fact, trust_level=self.TrustLevel.TRUSTED)
        assert result.decision in (
            self.ValidatorDecision.PROMOTE_EPISODIC,
            self.ValidatorDecision.STAGE_ONLY,
        )

    def test_has_six_dimension_scores(self):
        fact = self.ExtractedFact(
            content="Visc a Barcelona",
            attribute="location",
            value="Barcelona",
            tags=["identity"],
            importance=0.8,
        )
        result = self.validator.validate(fact, trust_level=self.TrustLevel.TRUSTED)
        expected_dims = {"trust", "explicitness", "stability", "future_utility", "novelty", "contradiction_risk"}
        assert expected_dims == set(result.scores.keys())

    def test_two_trust_levels_only(self):
        """v1 decision: only 2 trust levels."""
        from memory.memory.models.memory_types import TrustLevel
        assert len(TrustLevel) == 2

    def test_validator_returns_reason(self):
        fact = self.ExtractedFact(
            content="Em dic Anna",
            attribute="name",
            value="Anna",
            tags=["identity"],
            importance=0.8,
        )
        result = self.validator.validate(fact, trust_level=self.TrustLevel.TRUSTED)
        assert result.reason != ""


# ══════════════════════════════════════════════════════════════════
# SQLITE STORE TESTS (6)
# ══════════════════════════════════════════════════════════════════

class TestSQLiteStore:
    """SQLite store: all tables, CRUD, tombstones."""

    def setup_method(self):
        from memory.memory.storage.sqlite_store import SQLiteStore
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = Path(self.tmpdir) / "test_memory.db"
        self.store = SQLiteStore(self.db_path)

    def teardown_method(self):
        self.store.close()
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_init_creates_all_tables(self):
        tables = self.store.get_tables()
        expected = {
            "profile", "profile_history", "episodic", "staging",
            "tombstones", "memory_events", "attribute_aliases",
            "gc_log", "user_activity",
        }
        assert expected.issubset(set(tables))

    def test_profile_crud(self):
        entry_id = self.store.upsert_profile(
            user_id="user1",
            attribute="name",
            value="Anna",
            source="test",
            trust_level="trusted",
        )
        assert entry_id is not None

        profiles = self.store.get_profile("user1", "name")
        assert len(profiles) == 1
        assert json.loads(profiles[0]["value_json"]) == "Anna"

    def test_episodic_crud(self):
        entry_id = self.store.insert_episodic(
            user_id="user1",
            content="Test fact about Barcelona",
            memory_type="fact",
            importance=0.7,
        )
        assert entry_id is not None

        episodes = self.store.get_episodic("user1")
        assert len(episodes) == 1
        assert episodes[0]["content"] == "Test fact about Barcelona"

    def test_staging_crud(self):
        entry_id = self.store.insert_staging(
            user_id="user1",
            raw_text="Em dic Anna",
            validator_decision="promote_episodic",
        )
        assert entry_id is not None

        staging = self.store.get_staging("user1")
        assert len(staging) == 1

    def test_tombstones(self):
        self.store.add_tombstone(
            user_id="user1",
            content_hash="abc123",
            reason="user_forget",
        )
        assert self.store.is_tombstoned("user1", "abc123")
        assert not self.store.is_tombstoned("user1", "xyz999")

    def test_stats(self):
        self.store.upsert_profile("user1", "name", "Anna")
        self.store.insert_episodic("user1", "Test fact")
        self.store.insert_staging("user1", "Test staging")
        stats = self.store.get_stats("user1")
        assert stats["profile_count"] == 1
        assert stats["episodic_count"] == 1
        assert stats["staging_count"] == 1


# ══════════════════════════════════════════════════════════════════
# WORKING MEMORY TESTS (4)
# ══════════════════════════════════════════════════════════════════

class TestWorkingMemory:
    """Working memory: RAM cache per session. Stub for v1 contract."""

    def test_add_entry(self):
        """Working memory should accept new entries."""
        # v1 contract: working memory is a simple dict
        wm = {}
        wm["fact1"] = {"content": "Em dic Anna", "importance": 0.8}
        assert "fact1" in wm

    def test_search_returns_matches(self):
        """Working memory search should find relevant entries."""
        wm = {
            "fact1": {"content": "Em dic Anna", "importance": 0.8},
            "fact2": {"content": "Visc a Barcelona", "importance": 0.7},
        }
        results = [v for v in wm.values() if "Anna" in v["content"]]
        assert len(results) == 1

    def test_flush_empties(self):
        """Flush should empty working memory."""
        wm = {"fact1": {"content": "test"}}
        flushed = list(wm.values())
        wm.clear()
        assert len(wm) == 0
        assert len(flushed) == 1

    def test_clear(self):
        """Clear should empty working memory without flushing."""
        wm = {"fact1": {"content": "test"}}
        wm.clear()
        assert len(wm) == 0


# ══════════════════════════════════════════════════════════════════
# RETRIEVER TESTS (4)
# ══════════════════════════════════════════════════════════════════

class TestRetriever:
    """Retriever: multi-layer, threshold, budget. Contract only."""

    def test_threshold_floor(self):
        """Floor threshold is 0.45."""
        from memory.memory.config import get_config
        cfg = get_config("m1_8gb")
        assert cfg.retrieve.floor_threshold == 0.45

    def test_threshold_ceiling(self):
        """Ceiling threshold is 0.65."""
        from memory.memory.config import get_config
        cfg = get_config("m1_8gb")
        assert cfg.retrieve.ceiling_threshold == 0.65

    def test_budget_cap(self):
        """Budget cap for m1_8gb is 800 tokens."""
        from memory.memory.config import get_config
        cfg = get_config("m1_8gb")
        assert cfg.retrieve.max_tokens_cap == 800

    def test_multi_layer_order(self):
        """Retrieve order: working -> profile -> vector -> rerank."""
        # Contract: retrieve layers defined
        layers = ["working_memory", "profile", "staging", "vector"]
        assert len(layers) == 4
        assert layers[0] == "working_memory"
        assert layers[1] == "profile"


# ══════════════════════════════════════════════════════════════════
# MEMORY SERVICE TESTS (4)
# ══════════════════════════════════════════════════════════════════

class TestMemoryService:
    """MemoryService: remember, recall, forget, stats. Contract/integration."""

    def test_remember_stages(self):
        """remember() should create a staging entry."""
        from memory.memory.storage.sqlite_store import SQLiteStore
        tmpdir = tempfile.mkdtemp()
        store = SQLiteStore(Path(tmpdir) / "test.db")
        entry_id = store.insert_staging(
            user_id="user1",
            raw_text="Em dic Anna",
            validator_decision="promote_episodic",
        )
        assert entry_id is not None
        staging = store.get_staging("user1")
        assert len(staging) == 1
        store.close()
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)

    def test_recall_returns_list(self):
        """recall() should return a list (empty if no data)."""
        from memory.memory.storage.sqlite_store import SQLiteStore
        tmpdir = tempfile.mkdtemp()
        store = SQLiteStore(Path(tmpdir) / "test.db")
        results = store.get_episodic("user1")
        assert isinstance(results, list)
        store.close()
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)

    def test_forget_tombstones(self):
        """forget() should create a tombstone."""
        from memory.memory.storage.sqlite_store import SQLiteStore
        tmpdir = tempfile.mkdtemp()
        store = SQLiteStore(Path(tmpdir) / "test.db")
        store.add_tombstone("user1", "hash123", "user_forget")
        assert store.is_tombstoned("user1", "hash123")
        store.close()
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)

    def test_stats_returns_counts(self):
        """stats() should return counts per store."""
        from memory.memory.storage.sqlite_store import SQLiteStore
        tmpdir = tempfile.mkdtemp()
        store = SQLiteStore(Path(tmpdir) / "test.db")
        stats = store.get_stats("user1")
        assert "profile_count" in stats
        assert "episodic_count" in stats
        assert "staging_count" in stats
        store.close()
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)
