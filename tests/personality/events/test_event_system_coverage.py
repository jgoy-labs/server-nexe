"""
Tests for uncovered lines in personality/events/event_system.py.
Targets: 22 lines missing
"""
import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock
from personality.events.event_system import EventSystem, create_system_event
from personality.data.models import SystemEvent
from datetime import datetime, timezone


def _make_event(event_type="test"):
    return SystemEvent(
        timestamp=datetime.now(timezone.utc),
        source="test",
        event_type=event_type,
        details={}
    )


class TestEmitEvent:

    def test_emit_ignored_event_type(self):
        """Line 51: ignored event type is skipped."""
        es = EventSystem()
        es.ignore_event_type("skip_me")
        cb = MagicMock()
        es.add_event_listener(cb)

        asyncio.run(es.emit_event(_make_event("skip_me")))
        cb.assert_not_called()

    def test_emit_to_typed_callbacks(self):
        """Lines 58-59: typed callbacks are called."""
        es = EventSystem()
        cb = MagicMock()
        es.add_event_listener(cb, event_type="specific")

        asyncio.run(es.emit_event(_make_event("specific")))
        cb.assert_called_once()

    def test_emit_callback_exception_handled(self):
        """Lines 127-140: callback exception doesn't crash emit."""
        es = EventSystem()

        def bad_callback(event):
            raise Exception("callback error")

        es.add_event_listener(bad_callback)
        # Should not raise
        asyncio.run(es.emit_event(_make_event()))

    def test_emit_async_callback(self):
        """Lines 120-122: async callback is awaited."""
        es = EventSystem()
        called = []

        async def async_cb(event):
            called.append(event)

        es.add_event_listener(async_cb)
        asyncio.run(es.emit_event(_make_event()))
        assert len(called) == 1

    def test_emit_awaitable_result(self):
        """Lines 124-126: callback returns awaitable."""
        es = EventSystem()
        called = []

        async def coroutine_result():
            called.append(True)

        def cb(event):
            return coroutine_result()

        es.add_event_listener(cb)
        asyncio.run(es.emit_event(_make_event()))
        assert len(called) == 1


class TestEmitEventSync:

    def test_emit_sync_from_active_loop(self):
        """Lines 92-100: called from active event loop."""
        es = EventSystem()
        event = _make_event()

        async def _test():
            es.emit_event_sync(event)

        asyncio.run(_test())
        assert len(es.get_event_history()) == 1

    def test_emit_sync_no_loop(self):
        """Lines 104-105: no active loop, uses asyncio.run()."""
        es = EventSystem()
        event = _make_event()
        es.emit_event_sync(event)
        assert len(es.get_event_history()) == 1

    def test_emit_sync_exception(self):
        """Lines 106-114: emit_event raises in sync wrapper."""
        es = EventSystem()

        async def bad_emit(event):
            raise RuntimeError("emit failed")

        es.emit_event = bad_emit
        event = _make_event()

        with pytest.raises(RuntimeError):
            es.emit_event_sync(event)


class TestEventListeners:

    def test_remove_typed_callback(self):
        es = EventSystem()
        cb = MagicMock()
        es.add_event_listener(cb, event_type="typed")
        assert es.remove_event_listener(cb, event_type="typed") is True
        assert es.get_callback_count("typed") == 0

    def test_remove_typed_callback_cleanup(self):
        """Lines 191-192: empty typed list removed."""
        es = EventSystem()
        cb = MagicMock()
        es.add_event_listener(cb, event_type="typed")
        es.remove_event_listener(cb, event_type="typed")
        assert "typed" not in es._typed_callbacks

    def test_remove_nonexistent_callback(self):
        es = EventSystem()
        result = es.remove_event_listener(lambda e: None)
        assert result is False

    def test_clear_typed_listeners(self):
        """Lines 220-222: clear listeners for specific type."""
        es = EventSystem()
        es.add_event_listener(MagicMock(), event_type="specific")
        count = es.clear_event_listeners("specific")
        assert count == 1

    def test_clear_all_listeners(self):
        """Lines 223-229: clear all listeners."""
        es = EventSystem()
        es.add_event_listener(MagicMock())
        es.add_event_listener(MagicMock(), event_type="typed")
        count = es.clear_event_listeners()
        assert count == 2


class TestEventHistory:

    def test_max_history_truncation(self):
        """Lines 146-147: history exceeds max, oldest removed."""
        es = EventSystem()
        es.set_max_history(5)
        for i in range(10):
            asyncio.run(es.emit_event(_make_event(f"event_{i}")))
        assert len(es.get_event_history()) == 5

    def test_set_max_history_truncates_existing(self):
        """Lines 287-288: set_max_history truncates existing."""
        es = EventSystem()
        for i in range(10):
            es._add_to_history(_make_event(f"e_{i}"))
        es.set_max_history(3)
        assert len(es._event_history) == 3

    def test_get_event_history_filtered(self):
        """Lines 268-269: filter by event_type."""
        es = EventSystem()
        es._add_to_history(_make_event("a"))
        es._add_to_history(_make_event("b"))
        es._add_to_history(_make_event("a"))
        result = es.get_event_history(event_type="a")
        assert len(result) == 2

    def test_clear_event_history(self):
        es = EventSystem()
        es._add_to_history(_make_event())
        count = es.clear_event_history()
        assert count == 1
        assert len(es._event_history) == 0


class TestEventStats:

    def test_get_event_stats(self):
        es = EventSystem()
        es.add_event_listener(MagicMock(), event_type="test")
        es._add_to_history(_make_event("test"))
        stats = es.get_event_stats()
        assert stats["total_callbacks"] >= 1
        assert "test" in stats["event_type_counts"]

    def test_ignore_and_unignore(self):
        es = EventSystem()
        es.ignore_event_type("skip")
        assert "skip" in es.get_ignored_events()
        es.unignore_event_type("skip")
        assert "skip" not in es.get_ignored_events()


class TestCreateSystemEvent:

    def test_create_system_event(self):
        event = asyncio.run(create_system_event("source", "type", key="value"))
        assert event.source == "source"
        assert event.event_type == "type"
        assert event.details["key"] == "value"
