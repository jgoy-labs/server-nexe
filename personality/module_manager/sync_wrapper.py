"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: personality/module_manager/sync_wrapper.py
Description: Wrappers síncrons per operacions async del ModuleManager.

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
  Comprova si hi ha un event loop actiu.

  Returns:
    True si hi ha un event loop actiu
  """
  try:
    asyncio.get_running_loop()
    return True
  except RuntimeError:
    return False

def run_async_in_new_loop(coro) -> Any:
  """
  Executa una coroutine en un event loop nou.

  Args:
    coro: Coroutine a executar

  Returns:
    Resultat de la coroutine
  """
  return asyncio.run(coro)

def run_async_in_thread(coro) -> Any:
  """
  Executa una coroutine en un thread separat amb el seu propi event loop.

  Útil quan ja hi ha un event loop actiu i no podem usar asyncio.run().

  Args:
    coro: Coroutine a executar

  Returns:
    Resultat de la coroutine

  Raises:
    Exception: Si la coroutine falla
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
  Classe que proporciona wrappers síncrons per mètodes async.

  Permet cridar mètodes async del ModuleManager des de contextos
  síncrons (com create_app de FastAPI).
  """

  def __init__(self, i18n=None):
    """
    Inicialitza el wrapper.

    Args:
      i18n: I18nManager opcional per missatges
    """
    self.i18n = i18n

  def run_sync(self, coro, error_msg_key: str = 'sync_wrapper_failed') -> Any:
    """
    Executa una coroutine de forma síncrona.

    Detecta automàticament si hi ha un event loop actiu i
    utilitza l'estratègia adequada.

    Args:
      coro: Coroutine a executar
      error_msg_key: Clau del missatge d'error per i18n

    Returns:
      Resultat de la coroutine

    Raises:
      Exception: Si la coroutine falla
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
    """Log d'error amb i18n."""
    if self.i18n:
      msg = get_message(
        self.i18n,
        f'discovery.{msg_key}',
        error=str(error)
      )
      logger.error(msg, component="module_manager")