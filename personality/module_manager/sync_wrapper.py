"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: personality/module_manager/sync_wrapper.py
Description: Synchronous wrappers for ModuleManager async operations.

www.jgoy.net
────────────────────────────────────
"""

import asyncio
import logging
import threading
from typing import Dict, Any, TypeVar

from .messages import get_message

logger = logging.getLogger(__name__)
LOGGER_AVAILABLE = False

T = TypeVar('T')

def is_event_loop_running() -> bool:
  """
  Check if there is an active event loop.

  Returns:
    True if there is an active event loop
  """
  try:
    asyncio.get_running_loop()
    return True
  except RuntimeError:
    return False

def run_async_in_new_loop(coro) -> Any:
  """
  Run a coroutine in a new event loop.

  Args:
    coro: Coroutine to run

  Returns:
    Result of the coroutine
  """
  return asyncio.run(coro)

def run_async_in_thread(coro) -> Any:
  """
  Run a coroutine in a separate thread with its own event loop.

  Useful when an event loop is already running and we cannot use asyncio.run().

  Args:
    coro: Coroutine to run

  Returns:
    Result of the coroutine

  Raises:
    Exception: If the coroutine fails
  """
  result: Dict[str, Any] = {}
  error_holder: Dict[str, Exception] = {}

  def _run_in_thread():
    new_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(new_loop)
    try:
      result['value'] = new_loop.run_until_complete(coro)
    except Exception as exc:
      error_holder['exception'] = exc
    finally:
      try:
        new_loop.run_until_complete(new_loop.shutdown_asyncgens())
      finally:
        new_loop.close()

  thread = threading.Thread(
    target=_run_in_thread,
    name="async-sync-wrapper-thread"
  )
  thread.start()
  thread.join()

  if error_holder.get('exception') is not None:
    raise error_holder['exception']

  return result.get('value')

class SyncWrapper:
  """
  Class providing synchronous wrappers for async methods.

  Allows calling async ModuleManager methods from synchronous
  contexts (like FastAPI's create_app).
  """

  def __init__(self, i18n=None):
    """
    Initialize the wrapper.

    Args:
      i18n: Optional I18nManager for messages
    """
    self.i18n = i18n

  def run_sync(self, coro, error_msg_key: str = 'sync_wrapper_failed') -> Any:
    """
    Run a coroutine synchronously.

    Automatically detects if an event loop is active and
    uses the appropriate strategy.

    Args:
      coro: Coroutine to run
      error_msg_key: Error message key for i18n

    Returns:
      Result of the coroutine

    Raises:
      Exception: If the coroutine fails
    """
    if not is_event_loop_running():
      try:
        return run_async_in_new_loop(coro)
      except Exception as e:
        self._log_error(error_msg_key, e)
        raise
    else:
      try:
        return run_async_in_thread(coro)
      except Exception as e:
        self._log_error(error_msg_key, e)
        raise

  def _log_error(self, msg_key: str, error: Exception) -> None:
    """Log an error with i18n."""
    if LOGGER_AVAILABLE and self.i18n:
      msg = get_message(
        self.i18n,
        f'discovery.{msg_key}',
        error=str(error)
      )
      logger.error(msg, component="module_manager")
