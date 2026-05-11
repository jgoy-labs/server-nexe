"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: personality/module_manager/sync_wrapper.py
Description: Synchronous wrappers for async ModuleManager operations.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import asyncio
import threading
from typing import Dict, Any, TypeVar

from .messages import get_message

from personality._logger import get_logger
logger = get_logger(__name__)

T = TypeVar('T')

def is_event_loop_running() -> bool:
  """
  Check whether an event loop is currently running.

  Returns:
    True if an event loop is active
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
    Coroutine result
  """
  return asyncio.run(coro)

def run_async_in_thread(coro) -> Any:
  """
  Run a coroutine in a separate thread with its own event loop.

  Useful when an event loop is already active and asyncio.run() cannot be used.

  Args:
    coro: Coroutine to run

  Returns:
    Coroutine result

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
  Provides synchronous wrappers for async methods.

  Allows calling async ModuleManager methods from synchronous
  contexts (such as FastAPI's create_app).
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

    Automatically detects whether an event loop is active and
    uses the appropriate strategy.

    Args:
      coro: Coroutine to run
      error_msg_key: i18n error message key

    Returns:
      Coroutine result

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
    """Log an error with i18n support."""
    if self.i18n:
      msg = get_message(
        self.i18n,
        f'discovery.{msg_key}',
        error=str(error)
      )
      logger.error(msg, component="module_manager")