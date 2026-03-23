"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: personality/events/event_system.py
Description: Sistema global de gestió d'esdeveniments asíncrons per Nexe 0.8.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import inspect
import traceback
from typing import List, Callable, Any, Dict, Set
from datetime import datetime, timezone

from ..data.models import SystemEvent

from personality._logger import get_logger
logger = get_logger(__name__)

__all__ = ['EventSystem']

class EventSystem:
  """Global event management system for Nexe 0.8"""
  
  def __init__(self, i18n_manager=None):
    """
    Initialize event system.
    
    Args:
      i18n_manager: Optional I18nManager instance for translations
    """
    self.i18n = i18n_manager
    self._event_callbacks: List[Callable[[SystemEvent], None]] = []
    self._typed_callbacks: Dict[str, List[Callable]] = {}
    self._event_history: List[SystemEvent] = []
    self._max_history = 1000
    
    self._ignored_event_types: Set[str] = set()
    
  async def emit_event(self, event: SystemEvent) -> None:
    """
    Emit event to all registered callbacks with robust error handling.
    
    Args:
      event: SystemEvent to emit
    """
    if event.event_type in self._ignored_event_types:
      return
    
    self._add_to_history(event)
    
    await self._emit_to_callbacks(self._event_callbacks, event)
    
    typed_callbacks = self._typed_callbacks.get(event.event_type, [])
    await self._emit_to_callbacks(typed_callbacks, event)

  def emit_event_sync(self, event: SystemEvent) -> None:
    """
    Wrapper síncron per emit_event().

    Permet emetre events des de contextos síncrons creant un event loop temporal.

    Args:
      event: SystemEvent a emetre

    Raises:
      RuntimeError: Si es crida des d'un event loop ja actiu

    Notes:
      - Usa asyncio.run() per crear un event loop temporal
      - Si ja estàs dins d'un event loop, usar 'await emit_event()' directament

    **LIMITACIÓ IMPORTANT:**
      Si es crida des d'un context amb event loop actiu, l'event s'afegeix
      a l'historial però NO s'emet als callbacks (per evitar errors de loop).
      En aquests casos, usar 'await emit_event()' per emetre correctament.

    **Exemple d'ús correcte:**
      ```python
      event_system.emit_event_sync(event)

      await event_system.emit_event(event)

      ```
    """
    import asyncio

    try:
      loop = asyncio.get_running_loop()
      msg = self.i18n.t('sync.called_from_active_loop') if self.i18n else "emit_event_sync() called from active event loop"
      logger.warning(msg, component="event_system")
      self._add_to_history(event)
      msg = self.i18n.t('sync.added_to_history_only', event_type=event.event_type) if self.i18n else f"Event {event.event_type} added to history but not emitted (in active loop)"
      logger.info(msg, component="event_system")
      return
    except RuntimeError:
      pass

    try:
      asyncio.run(self.emit_event(event))
    except Exception as e:
      logger.error(
        "Failed to emit event sync: %s",
        e,
        component="event_system",
        exc_info=True
      )
      raise

  async def _emit_to_callbacks(self, callbacks: List[Callable], event: SystemEvent) -> None:
    """Emit event to a list of callbacks"""
    for callback in callbacks:
      try:
        if inspect.iscoroutinefunction(callback):
          await callback(event)
          continue

        result = callback(event)
        if inspect.isawaitable(result):
          await result
      except Exception as e:
        error_msg = "Error in event callback"
        
        if self.i18n:
          error_msg = self.i18n.t('module_manager.events.callback_error', error=str(e))
        
        logger.warning(error_msg, 
               component="event_system", 
               event_type=event.event_type,
               source=event.source,
               callback_name=getattr(callback, '__name__', 'anonymous'),
               exc_info=True, 
               stack_trace=traceback.format_exc())
  
  def _add_to_history(self, event: SystemEvent) -> None:
    """Add event to history with size management"""
    self._event_history.append(event)
    
    if len(self._event_history) > self._max_history:
      self._event_history.pop(0)
  
  def add_event_listener(self, callback: Callable[[SystemEvent], None], 
             event_type: str = None) -> None:
    """
    Register callback for system events.
    
    Args:
      callback: Function to call when event occurs
      event_type: Optional event type filter
    """
    if event_type:
      if event_type not in self._typed_callbacks:
        self._typed_callbacks[event_type] = []
      self._typed_callbacks[event_type].append(callback)
    else:
      self._event_callbacks.append(callback)
    
    callback_name = getattr(callback, '__name__', 'anonymous')
    logger.debug(
      self.i18n.t('module_manager.events.callback_registered', callback_name=callback_name) 
      if self.i18n else f"Event callback registered: {callback_name}",
      component="event_system", 
      callback_name=callback_name,
      event_type=event_type or "all",
      total_callbacks=len(self._event_callbacks) + sum(len(cb_list) for cb_list in self._typed_callbacks.values())
    )
  
  def remove_event_listener(self, callback: Callable[[SystemEvent], None], 
              event_type: str = None) -> bool:
    """
    Remove a registered callback.
    
    Args:
      callback: Callback to remove
      event_type: Event type if was registered with specific type
      
    Returns:
      True if callback was found and removed
    """
    try:
      if event_type and event_type in self._typed_callbacks:
        self._typed_callbacks[event_type].remove(callback)
        if not self._typed_callbacks[event_type]:
          del self._typed_callbacks[event_type]
      else:
        self._event_callbacks.remove(callback)
      
      callback_name = getattr(callback, '__name__', 'anonymous')
      logger.debug(
        self.i18n.t('module_manager.events.callback_removed', callback_name=callback_name)
        if self.i18n else f"Event callback removed: {callback_name}",
        component="event_system",
        callback_name=callback_name,
        event_type=event_type or "all"
      )
      return True
      
    except ValueError:
      return False
  
  def clear_event_listeners(self, event_type: str = None) -> int:
    """
    Clear event listeners.
    
    Args:
      event_type: Clear only listeners for specific event type, or all if None
      
    Returns:
      Number of callbacks cleared
    """
    if event_type:
      count = len(self._typed_callbacks.get(event_type, []))
      self._typed_callbacks.pop(event_type, None)
    else:
      count = len(self._event_callbacks)
      for type_list in self._typed_callbacks.values():
        count += len(type_list)
      
      self._event_callbacks.clear()
      self._typed_callbacks.clear()
    
    msg = self.i18n.t('module_manager.events.callbacks_cleared', count=count) if self.i18n else f"Cleared {count} event callbacks"
    logger.info(msg, component="event_system", cleared=count, event_type=event_type or "all")
    
    return count
  
  def get_callback_count(self, event_type: str = None) -> int:
    """
    Get number of registered callbacks.
    
    Args:
      event_type: Count for specific event type, or total if None
      
    Returns:
      Number of registered callbacks
    """
    if event_type:
      return len(self._typed_callbacks.get(event_type, []))
    else:
      total = len(self._event_callbacks)
      for type_list in self._typed_callbacks.values():
        total += len(type_list)
      return total
  
  def get_event_history(self, event_type: str = None, limit: int = 100) -> List[SystemEvent]:
    """
    Get event history.
    
    Args:
      event_type: Filter by event type
      limit: Maximum number of events to return
      
    Returns:
      List of recent events
    """
    events = self._event_history
    
    if event_type:
      events = [e for e in events if e.event_type == event_type]
    
    return events[-limit:] if events else []
  
  def clear_event_history(self) -> int:
    """Clear event history"""
    count = len(self._event_history)
    self._event_history.clear()
    
    logger.info("Event history cleared: %s events", count, component="event_system")

    return count
  
  def set_max_history(self, max_size: int) -> None:
    """Set maximum history size"""
    self._max_history = max(1, max_size)
    
    if len(self._event_history) > self._max_history:
      self._event_history = self._event_history[-self._max_history:]
  
  def ignore_event_type(self, event_type: str) -> None:
    """Add event type to ignore list"""
    self._ignored_event_types.add(event_type)
  
  def unignore_event_type(self, event_type: str) -> None:
    """Remove event type from ignore list"""
    self._ignored_event_types.discard(event_type)
  
  def get_ignored_events(self) -> Set[str]:
    """Get set of ignored event types"""
    return self._ignored_event_types.copy()
  
  def get_event_stats(self) -> Dict[str, Any]:
    """Get event system statistics"""
    event_type_counts = {}
    for event in self._event_history:
      event_type_counts[event.event_type] = event_type_counts.get(event.event_type, 0) + 1
    
    return {
      "total_callbacks": self.get_callback_count(),
      "typed_callbacks": {et: len(cbs) for et, cbs in self._typed_callbacks.items()},
      "general_callbacks": len(self._event_callbacks),
      "history_size": len(self._event_history),
      "max_history": self._max_history,
      "event_type_counts": event_type_counts,
      "ignored_types": list(self._ignored_event_types)
    }

async def create_system_event(source: str, event_type: str, **details) -> SystemEvent:
  """
  Helper function to create system events.
  
  Args:
    source: Source component/module
    event_type: Type of event
    **details: Additional event details
    
  Returns:
    SystemEvent instance
  """
  from ..data.models import SystemEvent
  
  return SystemEvent(
    timestamp=datetime.now(timezone.utc),
    source=source,
    event_type=event_type,
    details=details
  )
