"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: personality/data/models.py
Description: Data models compartits de Nexe Core. Defineix Enums (ModuleState, SystemStatus,

www.jgoy.net
────────────────────────────────────
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Any, Set, Union

from pydantic import BaseModel, Field

__all__ = [
  'ModuleState',
  'SystemStatus',
  'HealthStatus',
  'ModuleInfo',
  'SystemEvent',
  'HealthCheck',
  'SystemMetrics',
  'EndpointInfo',
  'ModuleRegistration',
  'ConfigSection',
  'ValidationResult',
  'detect_dependency_cycles',
  'calculate_module_uptime',
  'get_module_state_display_name',
  'create_module_info',
  'create_system_event',
  'set_i18n_manager',
]

_i18n_manager = None

def set_i18n_manager(i18n_manager):
  """Set i18n manager for core models"""
  global _i18n_manager
  _i18n_manager = i18n_manager

def _t(key: str, **kwargs) -> str:
  """Internal translation helper with fallbacks"""
  if _i18n_manager:
    return _i18n_manager.t(key, **kwargs)
  
  fallbacks = {
    'core_models.module_states.unknown': 'Unknown',
    'core_models.module_states.discovered': 'Discovered',
    'core_models.module_states.loading': 'Loading',
    'core_models.module_states.loaded': 'Loaded',
    'core_models.module_states.starting': 'Starting',
    'core_models.module_states.running': 'Running',
    'core_models.module_states.stopping': 'Stopping',
    'core_models.module_states.stopped': 'Stopped',
    'core_models.module_states.error': 'Error',
    'core_models.module_states.disabled': 'Disabled',
    'core_models.files.manifest_toml': 'manifest.toml',
    'core_models.event_levels.info': 'info',
    'core_models.validation.dependency_cycle_found': 'Found cycle - return path from cycle start',
    'core_models.validation.uptime_calculation_comment': 'Uptime in seconds or None if not running'
  }
  
  message = fallbacks.get(key, key)
  try:
    return message.format(**kwargs)
  except (KeyError, ValueError):
    return message

class ModuleState(Enum):
  """Possible module states in the system"""
  UNKNOWN = "unknown"
  DISCOVERED = "discovered"
  LOADING = "loading"
  LOADED = "loaded"
  STARTING = "starting"
  RUNNING = "running"
  STOPPING = "stopping"
  STOPPED = "stopped"
  ERROR = "error"
  DISABLED = "disabled"

class SystemStatus(Enum):
  """Overall system status"""
  STARTING = "starting"
  RUNNING = "running"
  DEGRADED = "degraded"
  STOPPING = "stopping"
  STOPPED = "stopped"
  ERROR = "error"

class HealthStatus(Enum):
  """Health check status"""
  HEALTHY = "healthy"
  DEGRADED = "degraded"
  UNHEALTHY = "unhealthy"
  UNKNOWN = "unknown"

@dataclass
class ModuleInfo:
  """Complete module information"""
  name: str
  path: Path
  manifest_path: Path
  manifest: Dict[str, Any] = field(default_factory=dict)
  state: ModuleState = ModuleState.UNKNOWN
  priority: int = 10
  auto_start: bool = True
  enabled: bool = True
  
  instance: Optional[Any] = None
  load_time: Optional[datetime] = None
  start_time: Optional[datetime] = None
  error_count: int = 0
  last_error: Optional[str] = None
  dependencies: List[str] = field(default_factory=list)
  dependents: Set[str] = field(default_factory=set)
  
  api_calls: int = 0
  memory_usage_mb: float = 0.0
  cpu_usage: float = 0.0
  load_duration_ms: Optional[int] = None
  start_duration_ms: Optional[int] = None
  last_activity: Optional[datetime] = None
  
  api_prefix: Optional[str] = None
  ui_route: Optional[str] = None
  provides: Set[str] = field(default_factory=set)

class SystemEvent(BaseModel):
  """System-wide event"""
  timestamp: datetime
  source: str
  event_type: str
  details: Dict[str, Any] = Field(default_factory=dict)

  level: str = _t('core_models.event_levels.info')
  user_id: Optional[str] = None
  session_id: Optional[str] = None

ModuleEvent = SystemEvent

@dataclass
class HealthCheck:
  """Health check result"""
  name: str
  status: HealthStatus
  message: str
  details: Dict[str, Any] = field(default_factory=dict)
  timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
  duration_ms: Optional[int] = None

@dataclass
class SystemMetrics:
  """System-wide metrics snapshot"""
  timestamp: datetime
  total_modules: int
  running_modules: int
  total_memory_mb: float
  average_cpu_usage: float
  average_load_time_ms: float
  total_api_calls: int
  modules_with_errors: int
  states_breakdown: Dict[str, int]
  uptime_seconds: float

@dataclass
class EndpointInfo:
  """API endpoint information"""
  path: str
  method: str
  function: str
  module_name: str
  summary: Optional[str] = None
  tags: List[str] = field(default_factory=list)
  parameters: Dict[str, Any] = field(default_factory=dict)
  responses: Dict[str, Any] = field(default_factory=dict)

@dataclass 
class ModuleRegistration:
  """Complete module registry entry"""
  name: str
  instance: Any
  manifest: Dict[str, Any]
  registration_time: datetime
  endpoints: List[EndpointInfo] = field(default_factory=list)
  metadata: Dict[str, Any] = field(default_factory=dict)
  api_prefix: Optional[str] = None
  ui_route: Optional[str] = None
  dependencies: Set[str] = field(default_factory=set)
  provides: Set[str] = field(default_factory=set)

@dataclass
class ConfigSection:
  """Configuration section definition"""
  name: str
  required: bool = False
  description: str = ""
  schema: Dict[str, Any] = field(default_factory=dict)

@dataclass
class ValidationResult:
  """Configuration validation result"""
  valid: bool
  errors: List[str] = field(default_factory=list)
  warnings: List[str] = field(default_factory=list)
  section: Optional[str] = None

def detect_dependency_cycles(modules: Dict[str, ModuleInfo]) -> Optional[List[str]]:
  """
  Detect dependency cycles in module dependencies.
  
  Args:
    modules: Dictionary of module name -> ModuleInfo
    
  Returns:
    List of modules in cycle if found, None otherwise
  """
  visited = set()
  rec_stack = set()
  
  def visit(module_name: str, path: List[str]) -> Optional[List[str]]:
    if module_name in rec_stack:
      cycle_start = path.index(module_name)
      return path[cycle_start:] + [module_name]
    
    if module_name in visited:
      return None
    
    visited.add(module_name)
    rec_stack.add(module_name)
    
    if module_name in modules:
      for dep in modules[module_name].dependencies:
        cycle = visit(dep, path + [module_name])
        if cycle:
          return cycle
    
    rec_stack.remove(module_name)
    return None
  
  for module_name in modules:
    if module_name not in visited:
      cycle = visit(module_name, [])
      if cycle:
        return cycle
  
  return None

def calculate_module_uptime(module_info: ModuleInfo) -> Optional[float]:
  """
  Calculate module uptime in seconds.
  
  Args:
    module_info: Module information
    
  Returns:
    Uptime in seconds or None if not running (translated comment)
  """
  if module_info.start_time and module_info.state == ModuleState.RUNNING:
    from datetime import datetime, timezone
    delta = datetime.now(timezone.utc) - module_info.start_time
    return delta.total_seconds()
  return None

def get_module_state_display_name(state: ModuleState, i18n_manager=None) -> str:
  """
  Get display name for module state.
  
  Args:
    state: Module state
    i18n_manager: Optional i18n manager for translation
    
  Returns:
    Display name for the state
  """
  if i18n_manager:
    return i18n_manager.t(f'core_models.module_states.{state.value}')
  
  state_names = {
    ModuleState.UNKNOWN: _t('core_models.module_states.unknown'),
    ModuleState.DISCOVERED: _t('core_models.module_states.discovered'),
    ModuleState.LOADING: _t('core_models.module_states.loading'),
    ModuleState.LOADED: _t('core_models.module_states.loaded'),
    ModuleState.STARTING: _t('core_models.module_states.starting'),
    ModuleState.RUNNING: _t('core_models.module_states.running'),
    ModuleState.STOPPING: _t('core_models.module_states.stopping'),
    ModuleState.STOPPED: _t('core_models.module_states.stopped'),
    ModuleState.ERROR: _t('core_models.module_states.error'),
    ModuleState.DISABLED: _t('core_models.module_states.disabled')
  }
  
  return state_names.get(state, state.value.title())

def create_module_info(name: str, path: Union[str, Path], **kwargs) -> ModuleInfo:
  """
  Helper function to create ModuleInfo with defaults.
  
  Args:
    name: Module name
    path: Module path
    **kwargs: Additional ModuleInfo fields
    
  Returns:
    ModuleInfo instance
  """
  path = Path(path) if isinstance(path, str) else path
  manifest_filename = _t('core_models.files.manifest_toml')
  manifest_path = kwargs.pop('manifest_path', path / manifest_filename)
  
  return ModuleInfo(
    name=name,
    path=path,
    manifest_path=Path(manifest_path),
    **kwargs
  )

def create_system_event(source: str, event_type: str, level: str = None, **details) -> SystemEvent:
  """
  Helper function to create SystemEvent.
  
  Args:
    source: Event source
    event_type: Type of event
    level: Event level (info, warning, error, critical)
    **details: Additional event details
    
  Returns:
    SystemEvent instance
  """
  from datetime import datetime, timezone
  
  if level is None:
    level = _t('core_models.event_levels.info')
  
  return SystemEvent(
    timestamp=datetime.now(timezone.utc),
    source=source,
    event_type=event_type,
    level=level,
    details=details
  )

ModuleDict = Dict[str, ModuleInfo]
EventCallback = callable
ValidationErrors = List[str]
MetricsDict = Dict[str, Any]