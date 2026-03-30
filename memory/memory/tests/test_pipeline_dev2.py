"""
Tests del pipeline de memòria v1 — dev2 fase 1.
Gate, Extractor, Validator, Deduplicator.
Session: 20260330
"""

import pytest
from memory.memory.pipeline.gate import Gate, GateResult
from memory.memory.pipeline.extractor import Extractor
from memory.memory.pipeline.validator import Validator
from memory.memory.pipeline.deduplicator import Deduplicator
from memory.memory.pipeline.schema_enforcer import SchemaEnforcer
from memory.memory.models.memory_entry import ExtractedFact, MemoryEntry
from memory.memory.models.memory_types import (
    TrustLevel,
    ValidatorDecision,
    MemoryType,
)


# ──────────────────────────────────────────
# 2.1 Gate filtra brossa
# ──────────────────────────────────────────

class TestGateFiltraBrossa:
    """10 missatges trivials → ZERO passen el gate."""

    JUNK_MESSAGES = [
        "Hola!",
        "ok",
        "si",
        "no",
        "test test test",
        "???",
        "Que es Python?",
        "Explica ML",
        "Bon dia!",
        "Gracies",
    ]

    def setup_method(self):
        self.gate = Gate()

    @pytest.mark.parametrize("msg", JUNK_MESSAGES)
    def test_junk_message_rejected(self, msg):
        """Cada missatge trivial ha de ser rebutjat pel gate."""
        result = self.gate.evaluate(msg, is_user_message=True)
        assert not result.passed, (
            f"Gate hauria de rebutjar '{msg}' però ha passat "
            f"(reason={result.reason}, score={result.score})"
        )

    def test_all_junk_rejected_batch(self):
        """Cap dels 10 missatges trivials ha de passar."""
        passed = [
            msg
            for msg in self.JUNK_MESSAGES
            if self.gate.evaluate(msg, is_user_message=True).passed
        ]
        assert len(passed) == 0, f"Missatges que han passat indegudament: {passed}"

    def test_empty_rejected(self):
        result = self.gate.evaluate("", is_user_message=True)
        assert not result.passed
        assert result.reason == "empty"

    def test_whitespace_rejected(self):
        result = self.gate.evaluate("   ", is_user_message=True)
        assert not result.passed

    def test_model_generated_rejected(self):
        result = self.gate.evaluate(
            "Soc programador a Barcelona", is_user_message=False, is_mem_save=False
        )
        assert not result.passed
        assert result.reason == "model_generated"


# ──────────────────────────────────────────
# 2.2 Pipeline accepta fets
# ──────────────────────────────────────────

class TestGateAcceptaFets:
    """Missatges amb fets reals → passen el gate."""

    FACT_MESSAGES = [
        "Em dic Anna i tinc 30 anys",
        "Visc a Madrid, treballo a Google",
        "M'agrada rock, odio reggaeton",
        "Soc vegetariana des de fa 5 anys",
        "Parlo català, castellà, anglès",
    ]

    def setup_method(self):
        self.gate = Gate()

    @pytest.mark.parametrize("msg", FACT_MESSAGES)
    def test_fact_message_accepted(self, msg):
        """Missatge amb fets ha de passar el gate."""
        result = self.gate.evaluate(msg, is_user_message=True)
        assert result.passed, (
            f"Gate hauria d'acceptar '{msg}' però l'ha rebutjat "
            f"(reason={result.reason}, score={result.score})"
        )


class TestExtractorFets:
    """L'extractor extreu fets dels missatges."""

    def setup_method(self):
        self.extractor = Extractor()

    def test_extract_name_and_age(self):
        facts = self.extractor.extract("Em dic Anna i tinc 30 anys")
        attrs = {f.attribute for f in facts if f.attribute}
        assert "name" in attrs, f"No ha extret 'name'. Facts: {facts}"
        name_fact = next(f for f in facts if f.attribute == "name")
        assert "Anna" in name_fact.value

    def test_extract_location_and_company(self):
        facts = self.extractor.extract("Visc a Madrid, treballo a Google")
        attrs = {f.attribute for f in facts if f.attribute}
        assert "location" in attrs, f"No ha extret 'location'. Facts: {facts}"
        assert "company" in attrs, f"No ha extret 'company'. Facts: {facts}"

    def test_extract_preferences(self):
        facts = self.extractor.extract("M'agrada rock, odio reggaeton")
        tags_flat = [tag for f in facts for tag in f.tags]
        assert "preference" in tags_flat, f"No ha extret preferències. Facts: {facts}"

    def test_extract_identity(self):
        facts = self.extractor.extract("Soc vegetariana des de fa 5 anys")
        assert len(facts) > 0, "No ha extret cap fet"

    def test_extract_languages(self):
        facts = self.extractor.extract("Parlo català, castellà, anglès")
        attrs = {f.attribute for f in facts if f.attribute}
        assert "spoken_languages" in attrs, f"No ha extret idiomes. Facts: {facts}"


# ──────────────────────────────────────────
# 2.3 Dedup — 4 formulacions de Barcelona → màx 2 entries
# ──────────────────────────────────────────

class TestDedup:
    """4 formulacions del mateix fet → SHA256 no les detecta (bug conegut)."""

    BARCELONA_VARIANTS = [
        "Visc a Barcelona",
        "Soc de BCN",
        "La meva ciutat és Barcelona",
        "Barcelona és on visc",
    ]

    def setup_method(self):
        self.dedup = Deduplicator()

    def test_exact_duplicate_detected(self):
        """Duplicat exacte sí que es detecta."""
        entry = MemoryEntry(entry_type=MemoryType.EPISODIC, content="Visc a Barcelona")
        assert not self.dedup.is_duplicate(entry)
        assert self.dedup.is_duplicate(entry)  # segon cop → duplicat

    def test_semantic_variants_dedup(self):
        """4 variants semàntiques del mateix fet → màx 2 entries."""
        entries = [
            MemoryEntry(entry_type=MemoryType.EPISODIC, content=text)
            for text in self.BARCELONA_VARIANTS
        ]
        accepted = [e for e in entries if not self.dedup.is_duplicate(e)]
        assert len(accepted) <= 2, (
            f"Dedup ha acceptat {len(accepted)} de 4 variants "
            f"(màx 2 esperat). Accepted: {[e.content for e in accepted]}"
        )

    def test_content_hash_deterministic(self):
        h1 = Deduplicator.compute_content_hash("test")
        h2 = Deduplicator.compute_content_hash("test")
        assert h1 == h2

    def test_different_content_different_hash(self):
        h1 = Deduplicator.compute_content_hash("Visc a Barcelona")
        h2 = Deduplicator.compute_content_hash("Soc de BCN")
        assert h1 != h2


# ──────────────────────────────────────────
# 2.4 Correcció
# ──────────────────────────────────────────

class TestCorrection:
    """'Em dic Anna' → 'No, em dic Maria' → Maria sobreescriu Anna."""

    def setup_method(self):
        self.extractor = Extractor()
        self.validator = Validator()

    def test_correction_detected(self):
        """L'extractor detecta 'No, em dic Maria' com a correcció."""
        facts = self.extractor.extract("No, em dic Maria")
        corrections = [f for f in facts if f.is_correction]
        assert len(corrections) > 0, f"No ha detectat correcció. Facts: {facts}"
        assert corrections[0].attribute == "name"
        assert "Maria" in corrections[0].value

    def test_correction_upserts_profile(self):
        """El validator decideix UPSERT_PROFILE per una correcció de nom."""
        fact = ExtractedFact(
            content="No, em dic Maria",
            entity="user",
            attribute="name",
            value="Maria",
            tags=["correction"],
            importance=0.9,
            source="heuristic",
            is_correction=True,
        )
        result = self.validator.validate(
            fact, trust_level=TrustLevel.TRUSTED, existing_value="Anna"
        )
        assert result.decision == ValidatorDecision.UPSERT_PROFILE, (
            f"Esperava UPSERT_PROFILE, obtingut {result.decision}"
        )

    def test_correction_overwrites_previous(self):
        """Pipeline complet: Anna → Maria."""
        # Primer: Anna
        facts_anna = self.extractor.extract("Em dic Anna")
        anna_fact = next((f for f in facts_anna if f.attribute == "name"), None)
        assert anna_fact is not None
        assert "Anna" in anna_fact.value

        # Després: correcció a Maria
        facts_maria = self.extractor.extract("No, em dic Maria")
        maria_fact = next(
            (f for f in facts_maria if f.attribute == "name" or f.is_correction),
            None,
        )
        assert maria_fact is not None
        assert "Maria" in maria_fact.value

        # Validator amb existing_value="Anna"
        result = self.validator.validate(
            maria_fact,
            trust_level=TrustLevel.TRUSTED,
            existing_value="Anna",
        )
        assert result.decision == ValidatorDecision.UPSERT_PROFILE


# ──────────────────────────────────────────
# Validator decisions
# ──────────────────────────────────────────

class TestValidator:
    """Decisions del validator segons tipus de fet."""

    def setup_method(self):
        self.validator = Validator()

    def test_identity_fact_upserts_profile(self):
        fact = ExtractedFact(
            content="Em dic Anna",
            entity="user",
            attribute="name",
            value="Anna",
            tags=["identity"],
            importance=0.8,
            source="heuristic",
        )
        result = self.validator.validate(fact, trust_level=TrustLevel.TRUSTED)
        assert result.decision == ValidatorDecision.UPSERT_PROFILE

    def test_duplicate_value_rejected(self):
        """Mateix valor ja existent → rebutjat (novelty baixa)."""
        fact = ExtractedFact(
            content="Em dic Anna",
            entity="user",
            attribute="name",
            value="Anna",
            tags=["identity"],
            importance=0.8,
            source="heuristic",
        )
        result = self.validator.validate(
            fact, trust_level=TrustLevel.TRUSTED, existing_value="Anna"
        )
        assert result.decision == ValidatorDecision.REJECT

    def test_preference_episodic(self):
        fact = ExtractedFact(
            content="M'agrada rock",
            entity="user",
            attribute=None,
            value="rock",
            tags=["preference", "positive"],
            importance=0.6,
            source="heuristic",
        )
        result = self.validator.validate(fact, trust_level=TrustLevel.UNTRUSTED)
        assert result.decision in (
            ValidatorDecision.PROMOTE_EPISODIC,
            ValidatorDecision.STAGE_ONLY,
        )


# ──────────────────────────────────────────
# Schema Enforcer
# ──────────────────────────────────────────

class TestSchemaEnforcer:
    def setup_method(self):
        self.schema = SchemaEnforcer()

    def test_exact_resolve(self):
        canonical, method = self.schema.resolve("name")
        assert canonical == "name"
        assert method == "exact"

    def test_alias_resolve(self):
        canonical, method = self.schema.resolve("nom")
        assert canonical == "name"
        assert method == "alias"

    def test_unknown_attribute(self):
        canonical, method = self.schema.resolve("color_favorit")
        assert canonical is None
        assert method == "none"

    def test_none_attribute(self):
        canonical, method = self.schema.resolve(None)
        assert canonical is None


# ──────────────────────────────────────────
# Coverage extra: Extractor health, preferences, _looks_factual
# ──────────────────────────────────────────

class TestExtractorHealth:
    """Health/allergy patterns."""

    def setup_method(self):
        self.extractor = Extractor()

    def test_allergy_detected(self):
        facts = self.extractor.extract("Tinc al·lèrgia a les nous")
        health = [f for f in facts if "health" in f.tags]
        assert len(health) > 0
        assert health[0].attribute == "allergies"

    def test_allergic_detected(self):
        facts = self.extractor.extract("Soc al·lèrgic al gluten")
        health = [f for f in facts if "health" in f.tags]
        assert len(health) > 0

    def test_allergy_english(self):
        facts = self.extractor.extract("I have an allergy to peanuts")
        health = [f for f in facts if "health" in f.tags]
        assert len(health) > 0


class TestExtractorPreferences:
    """Preference patterns."""

    def setup_method(self):
        self.extractor = Extractor()

    def test_negative_preference(self):
        facts = self.extractor.extract("Odio el reggaeton amb passió")
        neg = [f for f in facts if "negative" in f.tags]
        assert len(neg) > 0

    def test_prefer_pattern(self):
        facts = self.extractor.extract("Prefereixo treballar de nit")
        pos = [f for f in facts if "positive" in f.tags]
        assert len(pos) > 0

    def test_love_pattern(self):
        facts = self.extractor.extract("M'encanta el jazz")
        pos = [f for f in facts if "positive" in f.tags]
        assert len(pos) > 0


class TestExtractorLooksFactual:
    """_looks_factual fallback."""

    def setup_method(self):
        self.extractor = Extractor()

    def test_factual_no_pattern_match(self):
        """Text factual que no fa match amb cap pattern específic → generic fact."""
        facts = self.extractor.extract("Faig servir Linux cada dia per treballar")
        assert len(facts) > 0
        assert any("general" in f.tags for f in facts)

    def test_empty_text(self):
        facts = self.extractor.extract("")
        assert len(facts) == 0

    def test_non_factual_long_text(self):
        """Text llarg però no factual → pot no generar facts."""
        facts = self.extractor.extract("El cel és blau i les flors són boniques")
        # No hauria de generar facts (no identity, no preference, no factual markers)
        factual_markers = any("general" in f.tags for f in facts)
        identity_facts = any("identity" in f.tags for f in facts)
        assert not identity_facts  # No és un fet d'identitat


class TestExtractorEdgeCases:
    def setup_method(self):
        self.extractor = Extractor()

    def test_short_value_ignored(self):
        """Values massa curts s'ignoren."""
        facts = self.extractor.extract("I work at X")
        companies = [f for f in facts if f.attribute == "company"]
        # "X" is len 1, should be ignored
        assert len(companies) == 0

    def test_age_extraction(self):
        facts = self.extractor.extract("Tinc 25 anys")
        age = [f for f in facts if f.attribute == "birth_year"]
        assert len(age) > 0
        assert age[0].value == "25"


class TestGateEdgeCases:
    def setup_method(self):
        self.gate = Gate()

    def test_repetitive_content(self):
        result = self.gate.evaluate("test test test test test test test test", is_user_message=True)
        assert not result.passed
        assert result.reason == "repetitive"

    def test_mem_save_passes(self):
        result = self.gate.evaluate(
            "User likes coffee and drinks it every morning",
            is_user_message=False,
            is_mem_save=True,
        )
        assert result.passed

    def test_pure_question_with_assertion(self):
        """Question amb assertion ha de passar."""
        result = self.gate.evaluate(
            "Recordes que soc programador?", is_user_message=True
        )
        assert result.passed

    def test_high_importance_short(self):
        """Missatge curt però amb pattern important."""
        result = self.gate.evaluate("Soc enginyer", is_user_message=True)
        assert result.passed


# ──────────────────────────────────────────
# Integration: Gate → Extractor → Validator full flow
# ──────────────────────────────────────────

class TestPipelineFlow:
    """Test integrat Gate → Extractor → Validator."""

    def setup_method(self):
        self.gate = Gate()
        self.extractor = Extractor()
        self.validator = Validator()

    def test_junk_never_reaches_extractor(self):
        """Brossa filtrada pel gate no arriba a l'extractor."""
        junk = ["Hola!", "ok", "si", "???"]
        for msg in junk:
            gate_result = self.gate.evaluate(msg, is_user_message=True)
            assert not gate_result.passed

    def test_fact_flows_through_pipeline(self):
        """Fet real passa gate → extractor → validator."""
        msg = "Em dic Anna i tinc 30 anys"

        gate_result = self.gate.evaluate(msg, is_user_message=True)
        assert gate_result.passed

        facts = self.extractor.extract(msg)
        assert len(facts) > 0

        for fact in facts:
            if fact.attribute:
                result = self.validator.validate(
                    fact, trust_level=TrustLevel.TRUSTED
                )
                assert result.decision != ValidatorDecision.REJECT

    def test_correction_flows_through_pipeline(self):
        """Correcció passa gate → extractor (correction) → validator (upsert)."""
        msg = "No, em dic Maria"

        gate_result = self.gate.evaluate(msg, is_user_message=True)
        assert gate_result.passed, f"Gate ha rebutjat correcció: {gate_result.reason}"

        facts = self.extractor.extract(msg)
        corrections = [f for f in facts if f.is_correction]
        assert len(corrections) > 0

        result = self.validator.validate(
            corrections[0],
            trust_level=TrustLevel.TRUSTED,
            existing_value="Anna",
        )
        assert result.decision == ValidatorDecision.UPSERT_PROFILE
