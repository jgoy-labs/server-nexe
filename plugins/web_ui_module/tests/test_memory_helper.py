"""
Tests unitaris per MemoryHelper.
Sense GPU ni Qdrant — cobreix tota la lògica en memòria.
"""
import pytest
from datetime import datetime, timezone, timedelta

from plugins.web_ui_module.memory_helper import (
    MemoryHelper,
    SAVE_TRIGGERS,
    RECALL_PATTERNS,
    MEMORY_TYPES,
    SIMILARITY_THRESHOLD,
    TEMPORAL_DECAY_DAYS,
    MIN_IMPORTANCE_SCORE,
)


@pytest.fixture
def mh():
    return MemoryHelper()


# ═══════════════════════════════════════════════════════════════
# detect_intent — intent SAVE
# ═══════════════════════════════════════════════════════════════

class TestDetectIntentSave:

    def test_save_catala_pots_guardar(self, mh):
        intent, content = mh.detect_intent("El meu nom és Pere, ho pots guardar?")
        assert intent == "save"
        assert "Pere" in content

    def test_save_catala_guardaho(self, mh):
        intent, content = mh.detect_intent("Treballo a Barcelona, guarda-ho")
        assert intent == "save"
        assert "Barcelona" in content

    def test_save_catala_desaho(self, mh):
        intent, content = mh.detect_intent("Tinc 30 anys, desa-ho")
        assert intent == "save"
        assert "30" in content

    def test_save_catala_pots_recordar(self, mh):
        intent, content = mh.detect_intent("M'agrada el jazz, ho pots recordar?")
        assert intent == "save"
        assert "jazz" in content

    def test_save_espanyol_guardar(self, mh):
        intent, content = mh.detect_intent("Me llamo Ana, lo puedes guardar?")
        assert intent == "save"
        assert "Ana" in content

    def test_save_espanyol_guardalo(self, mh):
        intent, content = mh.detect_intent("Vivo en Madrid, guárdalo")
        assert intent == "save"
        assert "Madrid" in content

    def test_save_angles_save_it(self, mh):
        intent, content = mh.detect_intent("My name is John, save it")
        assert intent == "save"
        assert "John" in content

    def test_save_angles_remember_this(self, mh):
        intent, content = mh.detect_intent("I work as a developer, can you remember this?")
        assert intent == "save"
        assert "developer" in content

    def test_save_strips_trailing_comma(self, mh):
        intent, content = mh.detect_intent("Soc programador, ho pots guardar?")
        assert intent == "save"
        assert not content.endswith(",")

    def test_save_content_not_empty(self, mh):
        intent, content = mh.detect_intent("X, guarda-ho")
        assert intent == "save"
        assert content == "X"

    def test_save_returns_content_before_trigger(self, mh):
        intent, content = mh.detect_intent("La meva edat és 25, ho pots guardar?")
        assert intent == "save"
        assert "guardar" not in content


# ═══════════════════════════════════════════════════════════════
# detect_intent — intent RECALL
# ═══════════════════════════════════════════════════════════════

class TestDetectIntentRecall:

    def test_recall_catala_recordes(self, mh):
        intent, _ = mh.detect_intent("Recordes el meu nom?")
        assert intent == "recall"

    def test_recall_catala_que_saps(self, mh):
        intent, _ = mh.detect_intent("Què saps sobre mi?")
        assert intent == "recall"

    def test_recall_catala_com_em_dic(self, mh):
        intent, _ = mh.detect_intent("Com em dic?")
        assert intent == "recall"

    def test_recall_catala_quin_es_el_meu_nom(self, mh):
        intent, _ = mh.detect_intent("Quin és el meu nom?")
        assert intent == "recall"

    def test_recall_espanyol_recuerdas(self, mh):
        intent, _ = mh.detect_intent("¿Recuerdas cuál es mi nombre?")
        assert intent == "recall"

    def test_recall_espanyol_como_me_llamo(self, mh):
        intent, _ = mh.detect_intent("¿Cómo me llamo?")
        assert intent == "recall"

    def test_recall_angles_do_you_remember(self, mh):
        intent, _ = mh.detect_intent("Do you remember my preferences?")
        assert intent == "recall"

    def test_recall_angles_what_is_my_name(self, mh):
        intent, _ = mh.detect_intent("What's my name?")
        assert intent == "recall"

    def test_recall_angles_search(self, mh):
        intent, _ = mh.detect_intent("search for my notes")
        assert intent == "recall"

    def test_recall_returns_full_message(self, mh):
        msg = "Recordes la meva adreça?"
        intent, content = mh.detect_intent(msg)
        assert intent == "recall"
        assert content == msg


# ═══════════════════════════════════════════════════════════════
# detect_intent — intent CHAT (default)
# ═══════════════════════════════════════════════════════════════

class TestDetectIntentChat:

    def test_chat_normal_question(self, mh):
        intent, content = mh.detect_intent("Quin temps fa avui?")
        assert intent == "chat"
        assert content is None

    def test_chat_greeting(self, mh):
        intent, _ = mh.detect_intent("Hola, com estàs?")
        assert intent == "chat"

    def test_chat_calculation(self, mh):
        intent, _ = mh.detect_intent("Quant és 2+2?")
        assert intent == "chat"

    def test_chat_empty_message(self, mh):
        intent, _ = mh.detect_intent("")
        assert intent == "chat"

    def test_chat_unrelated_guardar(self, mh):
        # "guardar" al mig d'una frase no és trigger (els triggers van al FINAL)
        intent, _ = mh.detect_intent("Per guardar fitxers usa Ctrl+S")
        assert intent == "chat"


# ═══════════════════════════════════════════════════════════════
# _is_trivial_message
# ═══════════════════════════════════════════════════════════════

class TestIsTrivialMessage:

    def test_trivial_too_short(self, mh):
        assert mh._is_trivial_message("Ok") is True

    def test_trivial_greeting_hola(self, mh):
        assert mh._is_trivial_message("Hola, com estàs?") is True

    def test_trivial_greeting_hello(self, mh):
        assert mh._is_trivial_message("Hello there!") is True

    def test_trivial_thanks_gracies(self, mh):
        assert mh._is_trivial_message("Gràcies per la resposta") is True

    def test_trivial_thanks_gracias(self, mh):
        assert mh._is_trivial_message("Gracias por ayudar") is True

    def test_trivial_ok_vale(self, mh):
        assert mh._is_trivial_message("vale, entendido") is True

    def test_not_trivial_meaningful(self, mh):
        assert mh._is_trivial_message("El meu nom és Jordi i treballo a Barcelona") is False

    def test_not_trivial_question(self, mh):
        assert mh._is_trivial_message("Quin és el millor framework per a web?") is False

    def test_trivial_exactly_9_chars(self, mh):
        assert mh._is_trivial_message("123456789") is True  # len < 10

    def test_not_trivial_exactly_10_chars(self, mh):
        # Only short check, no pattern match
        msg = "1234567890"
        # len >= 10 AND no pattern match → not trivial
        assert mh._is_trivial_message(msg) is False


# ═══════════════════════════════════════════════════════════════
# _apply_temporal_decay
# ═══════════════════════════════════════════════════════════════

class TestApplyTemporalDecay:

    def test_recent_gets_bonus(self, mh):
        meta = {"saved_at": datetime.now(timezone.utc).isoformat()}
        adjusted = mh._apply_temporal_decay(0.7, meta)
        assert adjusted >= 0.7  # recent = bonus

    def test_very_old_gets_penalty(self, mh):
        old = datetime.now(timezone.utc) - timedelta(days=TEMPORAL_DECAY_DAYS * 5)
        meta = {"saved_at": old.isoformat()}
        adjusted = mh._apply_temporal_decay(0.7, meta)
        assert adjusted <= 0.7  # old = penalty

    def test_no_saved_at_returns_original(self, mh):
        score = 0.65
        adjusted = mh._apply_temporal_decay(score, {})
        assert adjusted == score

    def test_invalid_date_returns_original(self, mh):
        score = 0.5
        adjusted = mh._apply_temporal_decay(score, {"saved_at": "not-a-date"})
        assert adjusted == score

    def test_adjusted_never_exceeds_1(self, mh):
        meta = {"saved_at": datetime.now(timezone.utc).isoformat()}
        adjusted = mh._apply_temporal_decay(0.99, meta)
        assert adjusted <= 1.0

    def test_naive_datetime_handled(self, mh):
        # Naive datetime (sense tzinfo) ha de funcionar
        naive = datetime.now().isoformat()
        meta = {"saved_at": naive}
        result = mh._apply_temporal_decay(0.6, meta)
        assert isinstance(result, float)


# ═══════════════════════════════════════════════════════════════
# _calculate_retention_score
# ═══════════════════════════════════════════════════════════════

class TestCalculateRetentionScore:

    class FakeEntry:
        def __init__(self, metadata):
            self.metadata = metadata

    def test_fact_higher_than_conversation(self, mh):
        fact = self.FakeEntry({"type": "fact", "access_count": 0, "saved_at": ""})
        conv = self.FakeEntry({"type": "conversation", "access_count": 0, "saved_at": ""})
        assert mh._calculate_retention_score(fact) > mh._calculate_retention_score(conv)

    def test_high_access_count_higher_score(self, mh):
        low = self.FakeEntry({"type": "contextual", "access_count": 0, "saved_at": ""})
        high = self.FakeEntry({"type": "contextual", "access_count": 10, "saved_at": ""})
        assert mh._calculate_retention_score(high) > mh._calculate_retention_score(low)

    def test_score_between_0_and_1(self, mh):
        entry = self.FakeEntry({"type": "fact", "access_count": 5, "saved_at": datetime.now(timezone.utc).isoformat()})
        score = mh._calculate_retention_score(entry)
        assert 0.0 <= score <= 1.0

    def test_unknown_type_uses_default(self, mh):
        entry = self.FakeEntry({"type": "unknown_xyz", "access_count": 0, "saved_at": ""})
        score = mh._calculate_retention_score(entry)
        assert isinstance(score, float)

    def test_empty_metadata_returns_default(self, mh):
        entry = self.FakeEntry({})
        score = mh._calculate_retention_score(entry)
        assert isinstance(score, float)

    def test_none_metadata_returns_default(self, mh):
        entry = self.FakeEntry(None)
        score = mh._calculate_retention_score(entry)
        assert isinstance(score, float)

    def test_memory_types_ordering(self, mh):
        """fact > preference > contextual > conversation"""
        def score_for(t):
            return mh._calculate_retention_score(
                self.FakeEntry({"type": t, "access_count": 0, "saved_at": ""})
            )
        assert score_for("fact") > score_for("preference")
        assert score_for("preference") > score_for("contextual")
        assert score_for("contextual") > score_for("conversation")


# ═══════════════════════════════════════════════════════════════
# Constants de configuració
# ═══════════════════════════════════════════════════════════════

class TestConstants:

    def test_similarity_threshold_range(self):
        assert 0.0 < SIMILARITY_THRESHOLD < 1.0

    def test_temporal_decay_positive(self):
        assert TEMPORAL_DECAY_DAYS > 0

    def test_memory_types_have_weights(self):
        for t, w in MEMORY_TYPES.items():
            assert 0.0 < w <= 1.0

    def test_save_triggers_non_empty(self):
        assert len(SAVE_TRIGGERS) > 0

    def test_recall_patterns_non_empty(self):
        assert len(RECALL_PATTERNS) > 0
