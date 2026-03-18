"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: personality/module_manager/module_lifecycle.py
Description: Gestor de cicle de vida de mòduls individuals. Controla load, start, stop amb

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import asyncio
import time
from datetime import datetime, timezone
from typing import Dict

from personality.data.models import ModuleState, SystemEvent
from .messages import get_message

from personality._logger import get_logger
logger = get_logger(__name__)
LOGGER_AVAILABLE = True

class ModuleLifecycleManager:
  """Gestiona cicle de vida de mòduls individuals"""

  def __init__(self, modules: Dict, loader, registry, events, metrics, i18n=None):
    """
    Inicialitza gestor de cicle de vida.

    Args:
      modules: Diccionari de mòduls
      loader: ModuleLoader
      registry: ModuleRegistry
      events: EventSystem
      metrics: MetricsCollector
      i18n: Gestor i18n opcional
    """
    self.modules = modules
    self.loader = loader
    self.registry = registry
    self.events = events
    self.metrics = metrics
    self.i18n = i18n
    self.api_integrator = None
    self._async_lock = asyncio.Lock()

  def set_api_integrator(self, api_integrator):
    """Estableix API integrator"""
    self.api_integrator = api_integrator

  async def load_module(self, module_name: str) -> bool:
    """
    Carrega un mòdul.

    Args:
      module_name: Nom del mòdul a carregar
      lock: Lock de threading

    Returns:
      True si s'ha carregat correctament
    """
    async with self._async_lock:
      if module_name not in self.modules:
        return False

      module_info = self.modules[module_name]

      if module_info.state in [ModuleState.LOADED, ModuleState.RUNNING]:
        return True

      if not module_info.enabled:
        if LOGGER_AVAILABLE:
          msg = get_message(self.i18n, 'loading.disabled',
                  module=module_name)
          logger.warning(msg, component="module_lifecycle")
        return False

      if module_info.state == ModuleState.LOADING:
        return False

    for dep in module_info.dependencies:
      if not await self.load_module(dep):
        if LOGGER_AVAILABLE:
          msg = get_message(self.i18n, 'loading.dependency_failed',
                  dep=dep, module=module_name)
          logger.error(msg, component="module_lifecycle")
        return False

    try:
      async with self._async_lock:
        module_info.state = ModuleState.LOADING

      if LOGGER_AVAILABLE:
        msg = get_message(self.i18n, 'loading.loading',
                module=module_name)
        logger.info(msg, component="module_lifecycle")

      start_time = time.time()
      instance = await self.loader.load_module(module_info)
      load_duration = int((time.time() - start_time) * 1000)

      async with self._async_lock:
        module_info.instance = instance
        module_info.load_time = datetime.now(timezone.utc)
        module_info.state = ModuleState.LOADED
        module_info.load_duration_ms = load_duration
        module_info.error_count = 0
        module_info.last_error = None

        for dep in module_info.dependencies:
          if dep in self.modules:
            self.modules[dep].dependents.add(module_name)

      self.registry.register_module(module_name, instance,
                     module_info.manifest)

      if self.api_integrator:
        try:
          self.api_integrator.integrate_module_api(
            module_name, instance, module_info
          )
        except Exception as e:
          if LOGGER_AVAILABLE:
            msg = get_message(self.i18n, 'api.integration.failed',
                    module=module_name, error=str(e))
            logger.warning(msg)

      await self.events.emit_event(SystemEvent(
        timestamp=datetime.now(timezone.utc),
        source="module_lifecycle",
        event_type="module_loaded",
        details={"module": module_name, "duration_ms": load_duration}
      ))

      self.metrics.update_module_metrics(self.modules, module_name,
                       load_duration_ms=load_duration)

      if LOGGER_AVAILABLE:
        msg = get_message(self.i18n, 'loading.loaded',
                module=module_name)
        logger.info(msg, component="module_lifecycle",
             duration_ms=load_duration)

      return True

    except Exception as e:
      async with self._async_lock:
        module_info.state = ModuleState.ERROR
        module_info.error_count += 1
        module_info.last_error = str(e)

      if LOGGER_AVAILABLE:
        msg = get_message(self.i18n, 'loading.error',
                module=module_name, error=str(e))
        logger.error(msg, component="module_lifecycle", exc_info=True)

      return False

  async def start_module(self, module_name: str) -> bool:
    """
    Inicia un mòdul carregat.

    Args:
      module_name: Nom del mòdul
      lock: Lock de threading

    Returns:
      True si s'ha iniciat correctament
    """
    async with self._async_lock:
      if module_name not in self.modules:
        return False

      module_info = self.modules[module_name]

      if module_info.state == ModuleState.RUNNING:
        return True

      if module_info.state != ModuleState.LOADED:
        if not await self.load_module(module_name):
          return False
        module_info = self.modules[module_name]

    try:
      async with self._async_lock:
        module_info.state = ModuleState.STARTING

      if LOGGER_AVAILABLE:
        msg = get_message(self.i18n, 'starting.starting',
                module=module_name)
        logger.info(msg, component="module_lifecycle")

      start_time = time.time()
      if hasattr(module_info.instance, 'start'):
        if asyncio.iscoroutinefunction(module_info.instance.start):
          await module_info.instance.start()
        else:
          module_info.instance.start()

      start_duration = int((time.time() - start_time) * 1000)

      async with self._async_lock:
        module_info.start_time = datetime.now(timezone.utc)
        module_info.state = ModuleState.RUNNING
        module_info.start_duration_ms = start_duration

      await self.events.emit_event(SystemEvent(
        timestamp=datetime.now(timezone.utc),
        source="module_lifecycle",
        event_type="module_started",
        details={"module": module_name, "duration_ms": start_duration}
      ))

      if LOGGER_AVAILABLE:
        msg = get_message(self.i18n, 'starting.started',
                module=module_name)
        logger.info(msg, component="module_lifecycle")

      return True

    except Exception as e:
      async with self._async_lock:
        module_info.state = ModuleState.ERROR
        module_info.error_count += 1
        module_info.last_error = str(e)

      if LOGGER_AVAILABLE:
        msg = get_message(self.i18n, 'starting.error',
                module=module_name, error=str(e))
        logger.error(msg, component="module_lifecycle", exc_info=True)

      return False

  async def stop_module(self, module_name: str) -> bool:
    """
    Atura un mòdul en execució.

    Args:
      module_name: Nom del mòdul
      lock: Lock de threading

    Returns:
      True si s'ha aturat correctament
    """
    async with self._async_lock:
      if module_name not in self.modules:
        return True

      module_info = self.modules[module_name]

      if module_info.state not in [ModuleState.RUNNING, ModuleState.LOADED]:
        return True

    try:
      async with self._async_lock:
        module_info.state = ModuleState.STOPPING

      if LOGGER_AVAILABLE:
        msg = get_message(self.i18n, 'stopping.stopping',
                module=module_name)
        logger.info(msg, component="module_lifecycle")

      if hasattr(module_info.instance, 'stop'):
        if asyncio.iscoroutinefunction(module_info.instance.stop):
          await module_info.instance.stop()
        else:
          module_info.instance.stop()

      await self.loader.unload_module(module_name)

      if self.api_integrator:
        try:
          self.api_integrator.remove_module_api(module_name)
        except Exception as e:
          if LOGGER_AVAILABLE:
            msg = get_message(self.i18n, 'api.removal.failed',
                    module=module_name, error=str(e))
            logger.warning(msg)

      self.registry.unregister_module(module_name)

      async with self._async_lock:
        module_info.state = ModuleState.STOPPED
        module_info.start_time = None
        module_info.instance = None

      await self.events.emit_event(SystemEvent(
        timestamp=datetime.now(timezone.utc),
        source="module_lifecycle",
        event_type="module_stopped",
        details={"module": module_name}
      ))

      if LOGGER_AVAILABLE:
        msg = get_message(self.i18n, 'stopping.stopped',
                module=module_name)
        logger.info(msg, component="module_lifecycle")

      return True

    except Exception as e:
      if LOGGER_AVAILABLE:
        msg = get_message(self.i18n, 'stopping.error',
                module=module_name, error=str(e))
        logger.error(msg, component="module_lifecycle", exc_info=True)

      return False