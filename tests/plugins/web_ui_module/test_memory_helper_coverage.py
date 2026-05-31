"""Tests for plugins/web_ui_module/core/memory_helper.py — coverage gaps."""


class TestMemoryHelperConstants:
    def test_max_memory_entries(self):
        from plugins.web_ui_module.core.memory_helper import MAX_MEMORY_ENTRIES
        assert MAX_MEMORY_ENTRIES > 0

    def test_similarity_threshold(self):
        from plugins.web_ui_module.core.memory_helper import SIMILARITY_THRESHOLD
        assert 0 < SIMILARITY_THRESHOLD < 1

    def test_memory_types(self):
        from plugins.web_ui_module.core.memory_helper import MEMORY_TYPES
        assert "fact" in MEMORY_TYPES
        assert "preference" in MEMORY_TYPES
        assert "contextual" in MEMORY_TYPES
        assert MEMORY_TYPES["fact"] == 1.0


class TestMemoryHelperInit:
    def test_init(self):
        from plugins.web_ui_module.core.memory_helper import MemoryHelper
        helper = MemoryHelper()
        assert helper is not None

    def test_detect_intent_chat(self):
        from plugins.web_ui_module.core.memory_helper import MemoryHelper
        helper = MemoryHelper()
        intent, _ = helper.detect_intent("Hello, how are you?")
        assert intent == "chat"

    def test_detect_intent_save(self):
        from plugins.web_ui_module.core.memory_helper import MemoryHelper
        helper = MemoryHelper()
        intent, _ = helper.detect_intent("My name is Alex, save it")
        assert intent == "save"

    def test_detect_intent_recall(self):
        from plugins.web_ui_module.core.memory_helper import MemoryHelper
        helper = MemoryHelper()
        intent, _ = helper.detect_intent("Recall my name please")
        assert intent in ("recall", "list", "chat")

    def test_is_trivial_message(self):
        from plugins.web_ui_module.core.memory_helper import MemoryHelper
        helper = MemoryHelper()
        assert helper._is_trivial_message("hi") is True
        assert helper._is_trivial_message("My name is Alex and I work at Acme Corp") is False

    def test_get_memory_helper_singleton(self):
        from plugins.web_ui_module.core.memory_helper import get_memory_helper
        h1 = get_memory_helper()
        h2 = get_memory_helper()
        assert h1 is h2
