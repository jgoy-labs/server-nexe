"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: personality/events/tests/test_event_system.py
Description: Tests per EventSystem. Valida publish-subscribe, emissió d'events,

www.jgoy.net
────────────────────────────────────
"""

import pytest
import asyncio
from datetime import datetime, timezone
from unittest.mock import MagicMock, AsyncMock

from personality.events.event_system import EventSystem, create_system_event
from personality.data.models import SystemEvent

@pytest.fixture
def event_system():
  """Create EventSystem instance."""
  return EventSystem()

@pytest.fixture
def sample_event():
  """Create sample SystemEvent."""
  return SystemEvent(
    timestamp=datetime.now(timezone.utc),
    source="test",
    event_type="test_event",
    details={"key": "value"}
  )

class TestEventSystemInit:
  """Tests for EventSystem initialization."""

  def test_init_default(self):
    """Should initialize with defaults."""
    es = EventSystem()

    assert es.i18n is None
    assert len(es._event_callbacks) == 0
    assert len(es._typed_callbacks) == 0
    assert len(es._event_history) == 0
    assert es._max_history == 1000

  def test_init_with_i18n(self):
    """Should store i18n manager."""
    mock_i18n = MagicMock()
    es = EventSystem(i18n_manager=mock_i18n)

    assert es.i18n == mock_i18n

class TestEventSystemEmit:
  """Tests for emit_event."""

  @pytest.mark.asyncio
  async def test_emit_adds_to_history(self, event_system, sample_event):
    """Should add event to history."""
    await event_system.emit_event(sample_event)

    assert len(event_system._event_history) == 1
    assert event_system._event_history[0] == sample_event

  @pytest.mark.asyncio
  async def test_emit_calls_general_callbacks(self, event_system, sample_event):
    """Should call general callbacks."""
    callback = MagicMock()
    event_system.add_event_listener(callback)

    await event_system.emit_event(sample_event)

    callback.assert_called_once_with(sample_event)

  @pytest.mark.asyncio
  async def test_emit_calls_typed_callbacks(self, event_system, sample_event):
    """Should call typed callbacks for matching event."""
    callback = MagicMock()
    event_system.add_event_listener(callback, "test_event")

    await event_system.emit_event(sample_event)

    callback.assert_called_once_with(sample_event)

  @pytest.mark.asyncio
  async def test_emit_skips_non_matching_typed(self, event_system, sample_event):
    """Should skip callbacks for non-matching event type."""
    callback = MagicMock()
    event_system.add_event_listener(callback, "other_event")

    await event_system.emit_event(sample_event)

    callback.assert_not_called()

  @pytest.mark.asyncio
  async def test_emit_async_callback(self, event_system, sample_event):
    """Should handle async callbacks."""
    callback = AsyncMock()
    event_system.add_event_listener(callback)

    await event_system.emit_event(sample_event)

    callback.assert_called_once_with(sample_event)

  @pytest.mark.asyncio
  async def test_emit_handles_callback_error(self, event_system, sample_event):
    """Should handle callback errors gracefully."""
    bad_callback = MagicMock(side_effect=Exception("Callback error"))
    good_callback = MagicMock()
    event_system.add_event_listener(bad_callback)
    event_system.add_event_listener(good_callback)

    await event_system.emit_event(sample_event)

    bad_callback.assert_called_once()
    good_callback.assert_called_once()

  @pytest.mark.asyncio
  async def test_emit_ignored_event(self, event_system, sample_event):
    """Should skip ignored event types."""
    callback = MagicMock()
    event_system.add_event_listener(callback)
    event_system.ignore_event_type("test_event")

    await event_system.emit_event(sample_event)

    callback.assert_not_called()
    assert len(event_system._event_history) == 0

class TestEventSystemListeners:
  """Tests for listener management."""

  def test_add_general_listener(self, event_system):
    """Should add general listener."""
    callback = MagicMock()

    event_system.add_event_listener(callback)

    assert callback in event_system._event_callbacks

  def test_add_typed_listener(self, event_system):
    """Should add typed listener."""
    callback = MagicMock()

    event_system.add_event_listener(callback, "module_loaded")

    assert "module_loaded" in event_system._typed_callbacks
    assert callback in event_system._typed_callbacks["module_loaded"]

  def test_remove_general_listener(self, event_system):
    """Should remove general listener."""
    callback = MagicMock()
    event_system.add_event_listener(callback)

    result = event_system.remove_event_listener(callback)

    assert result is True
    assert callback not in event_system._event_callbacks

  def test_remove_typed_listener(self, event_system):
    """Should remove typed listener."""
    callback = MagicMock()
    event_system.add_event_listener(callback, "test_event")

    result = event_system.remove_event_listener(callback, "test_event")

    assert result is True
    assert "test_event" not in event_system._typed_callbacks

  def test_remove_nonexistent_listener(self, event_system):
    """Should return False for nonexistent listener."""
    callback = MagicMock()

    result = event_system.remove_event_listener(callback)

    assert result is False

  def test_clear_all_listeners(self, event_system):
    """Should clear all listeners."""
    event_system.add_event_listener(MagicMock())
    event_system.add_event_listener(MagicMock(), "typed")

    count = event_system.clear_event_listeners()

    assert count == 2
    assert len(event_system._event_callbacks) == 0
    assert len(event_system._typed_callbacks) == 0

  def test_clear_typed_listeners(self, event_system):
    """Should clear only typed listeners."""
    event_system.add_event_listener(MagicMock())
    event_system.add_event_listener(MagicMock(), "typed")

    count = event_system.clear_event_listeners("typed")

    assert count == 1
    assert len(event_system._event_callbacks) == 1
    assert "typed" not in event_system._typed_callbacks

  def test_get_callback_count_total(self, event_system):
    """Should return total callback count."""
    event_system.add_event_listener(MagicMock())
    event_system.add_event_listener(MagicMock())
    event_system.add_event_listener(MagicMock(), "typed")

    count = event_system.get_callback_count()

    assert count == 3

  def test_get_callback_count_typed(self, event_system):
    """Should return typed callback count."""
    event_system.add_event_listener(MagicMock())
    event_system.add_event_listener(MagicMock(), "typed")
    event_system.add_event_listener(MagicMock(), "typed")

    count = event_system.get_callback_count("typed")

    assert count == 2

class TestEventSystemHistory:
  """Tests for event history."""

  @pytest.mark.asyncio
  async def test_get_history(self, event_system):
    """Should return event history."""
    event1 = SystemEvent(
      timestamp=datetime.now(timezone.utc),
      source="test", event_type="type1", details={}
    )
    event2 = SystemEvent(
      timestamp=datetime.now(timezone.utc),
      source="test", event_type="type2", details={}
    )
    await event_system.emit_event(event1)
    await event_system.emit_event(event2)

    history = event_system.get_event_history()

    assert len(history) == 2

  @pytest.mark.asyncio
  async def test_get_history_filtered(self, event_system):
    """Should filter history by event type."""
    event1 = SystemEvent(
      timestamp=datetime.now(timezone.utc),
      source="test", event_type="type1", details={}
    )
    event2 = SystemEvent(
      timestamp=datetime.now(timezone.utc),
      source="test", event_type="type2", details={}
    )
    await event_system.emit_event(event1)
    await event_system.emit_event(event2)

    history = event_system.get_event_history(event_type="type1")

    assert len(history) == 1
    assert history[0].event_type == "type1"

  @pytest.mark.asyncio
  async def test_get_history_limited(self, event_system):
    """Should respect limit parameter."""
    for i in range(10):
      await event_system.emit_event(SystemEvent(
        timestamp=datetime.now(timezone.utc),
        source="test", event_type="test", details={"i": i}
      ))

    history = event_system.get_event_history(limit=5)

    assert len(history) == 5

  def test_clear_history(self, event_system):
    """Should clear event history."""
    event_system._event_history = [MagicMock(), MagicMock()]

    count = event_system.clear_event_history()

    assert count == 2
    assert len(event_system._event_history) == 0

  @pytest.mark.asyncio
  async def test_history_max_size(self, event_system):
    """Should respect max history size."""
    event_system.set_max_history(5)

    for i in range(10):
      await event_system.emit_event(SystemEvent(
        timestamp=datetime.now(timezone.utc),
        source="test", event_type="test", details={"i": i}
      ))

    assert len(event_system._event_history) == 5

  def test_set_max_history_trims(self, event_system):
    """Should trim history when setting smaller max."""
    event_system._event_history = [MagicMock() for _ in range(10)]

    event_system.set_max_history(5)

    assert len(event_system._event_history) == 5

  def test_set_max_history_minimum(self, event_system):
    """Should enforce minimum of 1."""
    event_system.set_max_history(0)

    assert event_system._max_history == 1

class TestEventSystemIgnore:
  """Tests for event ignoring."""

  def test_ignore_event_type(self, event_system):
    """Should add to ignore list."""
    event_system.ignore_event_type("debug")

    assert "debug" in event_system._ignored_event_types

  def test_unignore_event_type(self, event_system):
    """Should remove from ignore list."""
    event_system._ignored_event_types.add("debug")

    event_system.unignore_event_type("debug")

    assert "debug" not in event_system._ignored_event_types

  def test_unignore_nonexistent(self, event_system):
    """Should handle unignoring nonexistent type."""
    event_system.unignore_event_type("nonexistent")

  def test_get_ignored_events(self, event_system):
    """Should return copy of ignored events."""
    event_system._ignored_event_types = {"a", "b"}

    result = event_system.get_ignored_events()

    assert result == {"a", "b"}
    assert result is not event_system._ignored_event_types

class TestEventSystemStats:
  """Tests for get_event_stats."""

  @pytest.mark.asyncio
  async def test_get_stats(self, event_system):
    """Should return comprehensive stats."""
    event_system.add_event_listener(MagicMock())
    event_system.add_event_listener(MagicMock(), "typed")
    event_system.ignore_event_type("ignored")
    await event_system.emit_event(SystemEvent(
      timestamp=datetime.now(timezone.utc),
      source="test", event_type="test", details={}
    ))

    stats = event_system.get_event_stats()

    assert stats["total_callbacks"] == 2
    assert stats["general_callbacks"] == 1
    assert stats["typed_callbacks"] == {"typed": 1}
    assert stats["history_size"] == 1
    assert stats["max_history"] == 1000
    assert "test" in stats["event_type_counts"]
    assert "ignored" in stats["ignored_types"]

class TestEventSystemSyncEmit:
  """Tests for emit_event_sync."""

  def test_emit_sync_no_loop(self, event_system, sample_event):
    """Should work when no event loop is active."""
    callback = MagicMock()
    event_system.add_event_listener(callback)

    event_system.emit_event_sync(sample_event)

    callback.assert_called_once_with(sample_event)

  def test_emit_sync_adds_to_history(self, event_system, sample_event):
    """Should add event to history."""
    event_system.emit_event_sync(sample_event)

    assert len(event_system._event_history) == 1

class TestCreateSystemEvent:
  """Tests for create_system_event helper."""

  @pytest.mark.asyncio
  async def test_create_event(self):
    """Should create SystemEvent with correct fields."""
    event = await create_system_event(
      source="test_module",
      event_type="module_loaded",
      duration_ms=100
    )

    assert event.source == "test_module"
    assert event.event_type == "module_loaded"
    assert event.details == {"duration_ms": 100}
    assert event.timestamp is not None