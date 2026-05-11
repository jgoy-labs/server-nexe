"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: personality/module_manager/system_lifecycle.py
Description: Gestor de cicle de vida del sistema Nexe. Controla start_system (discovery +

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from personality.data.models import ModuleState
from .messages import get_message
from .types import SystemLifecycleConfig

from personality._logger import get_logger
logger = get_logger(__name__)

class SystemLifecycleManager:
  """Gestiona cicle de vida del sistema complet"""

  def __init__(self, config: SystemLifecycleConfig) -> None:
    """
    Inicialitza gestor de cicle de vida del sistema.

    Args:
      config: SystemLifecycleConfig amb modules, module_lifecycle, discovery_func,
              list_modules_func i i18n opcionals
    """
    self.modules = config.modules
    self.module_lifecycle = config.module_lifecycle
    self.discovery_func = config.discovery_func
    self.list_modules_func = config.list_modules_func
    self.i18n = config.i18n
    self._running = False

  async def start_system(self) -> bool:
    """
    Inicia el sistema complet.

    Returns:
      True si s'ha iniciat correctament
    """
    try:
      self._running = True

      msg = get_message(self.i18n, 'system.startup.initializing')
      logger.info(msg, component="system_lifecycle")

      discovered = await self.discovery_func(force=True)

      started = 0
      for module_info in self.list_modules_func():
        if module_info.auto_start and module_info.enabled:
          if await self.module_lifecycle.load_module(
            module_info.name
          ):
            if await self.module_lifecycle.start_module(
              module_info.name
            ):
              started += 1

      msg = get_message(self.i18n, 'system.startup.ready')
      logger.info(msg, component="system_lifecycle",
           discovered=len(discovered), started=started)

      return True

    except Exception as e:
      self._running = False
      msg = get_message(self.i18n, 'system.errors.critical',
              error=str(e))
      logger.error(msg, component="system_lifecycle", exc_info=True)
      return False

  async def shutdown_system(self) -> None:
    """Atura el sistema complet"""
    msg = get_message(self.i18n, 'system.shutdown.initiated')
    logger.info(msg, component="system_lifecycle")

    self._running = False

    running = self.list_modules_func(state_filter=ModuleState.RUNNING)
    for module_info in running:
      await self.module_lifecycle.stop_module(
        module_info.name
      )

    msg = get_message(self.i18n, 'system.shutdown.completed')
    logger.info(msg, component="system_lifecycle")

  def is_running(self) -> bool:
    """Return whether the system is running."""
    return self._running

  def _get_lock(self):
    """Get the context lock (will be injected)."""
    return None