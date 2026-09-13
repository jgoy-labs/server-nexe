"""Tests for core/memory_facts/helper.py — coverage gaps."""


class TestMemoryHelperConstants:
    def test_max_memory_entries(self):
        from core.memory_facts.helper import MAX_MEMORY_ENTRIES
        assert MAX_MEMORY_ENTRIES > 0

    def test_similarity_threshold(self):
        from core.memory_facts.helper import SIMILARITY_THRESHOLD
        assert 0 < SIMILARITY_THRESHOLD < 1

    def test_memory_types(self):
        from core.memory_facts.helper import MEMORY_TYPES
        assert "fact" in MEMORY_TYPES
        assert "preference" in MEMORY_TYPES
        assert "contextual" in MEMORY_TYPES
        assert MEMORY_TYPES["fact"] == 1.0


class TestMemoryHelperInit:
    def test_init(self):
        from core.memory_facts.helper import MemoryHelper
        helper = MemoryHelper()
        assert helper is not None

    def test_detect_intent_chat(self):
        from core.memory_facts.helper import MemoryHelper
        helper = MemoryHelper()
        intent, _ = helper.detect_intent("Hello, how are you?")
        assert intent == "chat"

    def test_detect_intent_save(self):
        from core.memory_facts.helper import MemoryHelper
        helper = MemoryHelper()
        intent, _ = helper.detect_intent("My name is Alex, save it")
        assert intent == "save"

    def test_detect_intent_recall(self):
        from core.memory_facts.helper import MemoryHelper
        helper = MemoryHelper()
        intent, _ = helper.detect_intent("Recall my name please")
        assert intent in ("recall", "list", "chat")

    def test_is_trivial_message(self):
        from core.memory_facts.helper import MemoryHelper
        helper = MemoryHelper()
        assert helper._is_trivial_message("hi") is True
        assert helper._is_trivial_message("My name is Alex and I work at Acme Corp") is False

    def test_attach_gives_one_helper_per_state(self):
        """What the module singleton used to guarantee, the attach now does."""
        from core.memory_facts import attach_memory_helper

        class _State:
            pass

        state = _State()
        assert attach_memory_helper(state) is attach_memory_helper(state)
