"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: personality/module_manager/__init__.py
Description: Package marker per ModuleManager (sistema complet de gestió de mòduls). Exporta

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from pathlib import Path

from .module_manager import ModuleManager
from .path_discovery import PathDiscovery
from .registry import ModuleRegistry, EndpointInfo, ModuleRegistration
from .config_validator import ConfigValidator, ValidationResult
from .config_manager import ConfigManager

from ..data.models import (
  ModuleState, ModuleInfo, SystemEvent, ModuleEvent,
  detect_dependency_cycles, create_module_info, create_system_event
)
from ..i18n.i18n_manager import I18nManager
from ..events.event_system import EventSystem
from ..metrics.metrics_collector import MetricsCollector
from ..loading.loader import ModuleLoader, ModuleValidationError

__version__ = "0.8.0"
__author__ = "Jordi Goy, Nexe AI"

__all__ = [
  'ModuleManager',
  'ModuleRegistry',
  'ModuleLoader',
  'PathDiscovery',
  'ConfigValidator',
  'ConfigManager',

  'I18nManager',
  'EventSystem',
  'MetricsCollector',

  'ModuleInfo',
  'SystemEvent',
  'ModuleEvent',
  'ModuleRegistration',
  'EndpointInfo',
  'ValidationResult',

  'ModuleState',

  'ModuleValidationError',

  'detect_dependency_cycles',
  'create_module_info',
  'create_system_event',
  'create_orchestrator',
  'get_default_config_path',
  'create_module_manager_with_config',
  'create_module_system',
  'create_validated_module_manager',
]

def create_orchestrator(config_path=None):
  """
  Create a ModuleManager instance with default configuration.

  Args:
    config_path: Path to config file (default: auto-detect)

  Returns:
    ModuleManager: Configured instance
  """
  if config_path is None:
    config_path = get_default_config_path()

  return ModuleManager(config_path)

def get_default_config_path():
  """
  Auto-detect path to server.toml config file

  Returns:
    Path: Path to config file
  """
  current = Path(__file__).parent

  while current != current.parent:
    config_file = current / "server.toml"
    if config_file.exists():
      return config_file
    current = current.parent

  search_paths = [
    Path("server.toml"),
    Path("personality/server.toml"),
    Path("config/server.toml"),
  ]

  for path in search_paths:
    if path.exists():
      return path.resolve()

  return Path("personality/server.toml")

def create_module_manager_with_config(config_dict=None, **kwargs):
  """
  Create ModuleManager with custom configuration.

  Args:
    config_dict: Custom configuration dictionary
    **kwargs: Additional ModuleManager arguments

  Returns:
    ModuleManager: Configured instance
  """
  config_path = kwargs.pop('config_path', None) or get_default_config_path()

  manager = ModuleManager(config_path)

  if config_dict:
    manager._config.update(config_dict)

  return manager

def create_module_system(config_path=None):
  """
  Legacy function name for backward compatibility.

  Args:
    config_path: Path to config file

  Returns:
    ModuleManager: Configured instance
  """
  return create_orchestrator(config_path)

def create_validated_module_manager(config_path=None, validate_config=True):
  """
  Create ModuleManager with optional configuration validation.

  Args:
    config_path: Path to config file
    validate_config: Whether to validate configuration

  Returns:
    ModuleManager: Configured instance

  Raises:
    ValueError: If configuration validation fails
  """
  if config_path is None:
    config_path = get_default_config_path()

  config_path = Path(config_path)

  if validate_config:
    validator = ConfigValidator()
    errors = validator.validate(config_path)

    if errors:
      raise ValueError(f"Configuration validation failed:\n" + "\n".join(errors))

  return ModuleManager(config_path)