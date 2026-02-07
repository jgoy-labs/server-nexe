"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: personality/module_manager/system_lifecycle.py
Description: Nexe system lifecycle manager. Controls start_system (discovery +

www.jgoy.net
────────────────────────────────────
"""

from personality.data.models import ModuleState
from .messages import get_message

import logging
logger = logging.getLogger(__name__)
LOGGER_AVAILABLE = False

class SystemLifecycleManager:
  """Manage the full system lifecycle."""

  def __init__(self, modules, module_lifecycle, discovery_func, list_modules_func,
         i18n=None):
    """
    Initialize the system lifecycle manager.

    Args:
      modules: Module dictionary
      module_lifecycle: ModuleLifecycleManager
      discovery_func: Function to discover modules
      list_modules_func: Function to list modules
      i18n: Optional i18n manager
    """
    self.modules = modules
    self.module_lifecycle = module_lifecycle
    self.discovery_func = discovery_func
    self.list_modules_func = list_modules_func
    self.i18n = i18n
    self._running = False

  async def start_system(self) -> bool:
    """
    Start the full system.

    Returns:
      True if started successfully
    """
    try:
      self._running = True

      if LOGGER_AVAILABLE:
        msg = get_message(self.i18n, 'system.startup.initializing')
        logger.info(msg, component="system_lifecycle")

      discovered = await self.discovery_func(force=True)

      started = 0
      for module_info in self.list_modules_func():
        if module_info.auto_start and module_info.enabled:
          if await self.module_lifecycle.load_module(
            module_info.name, self._get_lock()
          ):
            if await self.module_lifecycle.start_module(
              module_info.name, self._get_lock()
            ):
              started += 1

      if LOGGER_AVAILABLE:
        msg = get_message(self.i18n, 'system.startup.ready')
        logger.info(msg, component="system_lifecycle",
             discovered=len(discovered), started=started)

      return True

    except Exception as e:
      self._running = False
      if LOGGER_AVAILABLE:
        msg = get_message(self.i18n, 'system.errors.critical',
                error=str(e))
        logger.error(msg, component="system_lifecycle", exc_info=True)
      return False

  async def shutdown_system(self) -> None:
    """Stop the full system."""
    if LOGGER_AVAILABLE:
      msg = get_message(self.i18n, 'system.shutdown.initiated')
      logger.info(msg, component="system_lifecycle")

    self._running = False

    running = self.list_modules_func(state_filter=ModuleState.RUNNING)
    for module_info in running:
      await self.module_lifecycle.stop_module(
        module_info.name, self._get_lock()
      )

    if LOGGER_AVAILABLE:
      msg = get_message(self.i18n, 'system.shutdown.completed')
      logger.info(msg, component="system_lifecycle")

  def is_running(self) -> bool:
    """Return whether the system is running."""
    return self._running

  def _get_lock(self):
    """Get the context lock (injected later)."""
    return None
