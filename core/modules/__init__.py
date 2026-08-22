"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: core/modules/__init__.py
Description: The module system: what a module IS (protocol, manifest) and what
             loads it (discovery, registry, lifecycle, admission). Both used to
             live apart — the contract in core/modules/, the loading in
             core/modules/ — which read as "the loader is the protocol and the
             kernel is the loader". One package, one answer.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from pathlib import Path

from .module_manager import ModuleManager
from .path_discovery import PathDiscovery
from .registry import ModuleRegistry, EndpointInfo, ModuleRegistration
from .config_validator import ConfigValidator, ValidationResult
from .config_manager import ConfigManager

# The contract every module implements, formerly core.modules.
from .protocol import (
  NexeModule,
  NexeModuleWithRouter,
  NexeModuleWithSpecialists,
  ModuleMetadata,
  ModuleStatus,
  HealthStatus,
  HealthResult,
  SpecialistInfo,
  PluginLoadError,
  validate_module,
)
from .manifest_base import (
  create_lazy_manifest,
  install_lazy_manifest,
)

from personality.data.models import (
  ModuleState, ModuleInfo, SystemEvent, ModuleEvent,
  detect_dependency_cycles, create_module_info, create_system_event
)
from personality.i18n.i18n_manager import I18nManager
from personality.events.event_system import EventSystem
from personality.metrics.metrics_collector import MetricsCollector
from personality.loading.loader import ModuleLoader, ModuleValidationError

# The live project version, as core.modules exported it. The package used to
# carry a hardcoded "0.9.1" of its own, three minor versions behind and read by
# nobody — a leftover of the v0.9.1 bump (3c4932c8).
from core.version import __version__

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

  'NexeModule',
  'NexeModuleWithRouter',
  'NexeModuleWithSpecialists',
  'ModuleMetadata',
  'ModuleStatus',
  'HealthStatus',
  'HealthResult',
  'SpecialistInfo',
  'PluginLoadError',
  'validate_module',
  'create_lazy_manifest',
  'install_lazy_manifest',
  '__version__',
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
    manager._config.update(config_dict)  # pyright: ignore[reportAttributeAccessIssue]  # _config set dynamically by ModuleManager.__init__

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
      raise ValueError("Configuration validation failed:\n" + "\n".join(errors))  # pyright: ignore[reportCallIssue,reportArgumentType]  # ValidationResult iterates over str messages

  return ModuleManager(config_path)