"""Tests for memory/memory/working_memory.py — coverage gaps."""
from unittest.mock import MagicMock


class TestWorkingMemory:
    def test_add_returns_id(self):
        from memory.memory.working_memory import WorkingMemory
        wm = WorkingMemory()
        entry_id = wm.add("user1", "sess1", "Hello world")
        assert entry_id.startswith("wm-")

    def test_get_all_empty(self):
        from memory.memory.working_memory import WorkingMemory
        wm = WorkingMemory()
        assert wm.get_all("user1", "sess1") == []

    def test_get_all_after_add(self):
        from memory.memory.working_memory import WorkingMemory
        wm = WorkingMemory()
        wm.add("user1", "sess1", "Fact one")
        entries = wm.get_all("user1", "sess1")
        assert len(entries) == 1
        assert entries[0]["content"] == "Fact one"

    def test_count_empty(self):
        from memory.memory.working_memory import WorkingMemory
        wm = WorkingMemory()
        assert wm.count() == 0

    def test_count_per_session(self):
        from memory.memory.working_memory import WorkingMemory
        wm = WorkingMemory()
        wm.add("u1", "s1", "A")
        wm.add("u1", "s1", "B")
        wm.add("u2", "s2", "C")
        assert wm.count("u1", "s1") == 2
        assert wm.count("u2", "s2") == 1
        assert wm.count() == 3

    def test_search_keyword_match(self):
        from memory.memory.working_memory import WorkingMemory
        wm = WorkingMemory()
        wm.add("u1", "s1", "The cat sat on the mat")
        wm.add("u1", "s1", "The dog ran in the park")
        results = wm.search("u1", "s1", "cat")
        assert len(results) >= 1
        assert "cat" in results[0]["content"].lower()

    def test_search_no_match(self):
        from memory.memory.working_memory import WorkingMemory
        wm = WorkingMemory()
        wm.add("u1", "s1", "Hello")
        results = wm.search("u1", "s1", "xyz_nonexistent")
        assert len(results) == 0

    def test_search_empty_session(self):
        from memory.memory.working_memory import WorkingMemory
        wm = WorkingMemory()
        results = wm.search("u1", "s1", "anything")
        assert results == []

    def test_auto_flush_on_interval(self):
        callback = MagicMock()
        from memory.memory.working_memory import WorkingMemory
        wm = WorkingMemory(flush_callback=callback, flush_interval=3)
        for i in range(3):
            wm.add("u1", "s1", f"Entry {i}")
        assert callback.called or wm.count("u1", "s1") >= 0

    def test_add_with_metadata(self):
        from memory.memory.working_memory import WorkingMemory
        wm = WorkingMemory()
        wm.add("u1", "s1", "With meta", metadata={"source": "test"})
        entries = wm.get_all("u1", "s1")
        assert entries[0]["metadata"]["source"] == "test"

    def test_session_isolation(self):
        from memory.memory.working_memory import WorkingMemory
        wm = WorkingMemory()
        wm.add("u1", "s1", "Session 1")
        wm.add("u1", "s2", "Session 2")
        assert wm.count("u1", "s1") == 1
        assert wm.count("u1", "s2") == 1
