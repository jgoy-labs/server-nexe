"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: personality/module_manager/config_validator.py
Description: server.toml configuration validator. Checks required sections,

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Any, List, Optional
import tomllib  # uiri toml trunca multiline amb \[ en silenci (#834) — validar amb el parser bo
import re

@dataclass
class ValidationResult:
  """Configuration validation result"""
  valid: bool
  errors: List[str]
  warnings: List[str]
  section: Optional[str] = None

class ConfigValidator:
  """Enhanced validator for server.toml configuration"""
  
  REQUIRED_SECTIONS = ['meta', 'core', 'personality', 'plugins', 'storage']
  
  REQUIRED_KEYS = {
    'meta': ['version', 'environment'],
    'core.server': ['host', 'port'],
    'personality.orchestrator': ['modules_path'],
    'plugins.models': ['primary'],
    'storage.logging': ['level']
  }
  
  VALID_ENVIRONMENTS = ['development', 'staging', 'production']
  VALID_LOG_LEVELS = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
  
  def __init__(self, i18n_manager=None):
    """
    Initialize validator.
    
    Args:
      i18n_manager: Optional I18nManager for translations
    """
    self.i18n = i18n_manager
  
  def _get_message(self, msg_key: str, **kwargs) -> str:
    """Get translated message or fallback"""
    if self.i18n:
      return self.i18n.t(msg_key, **kwargs)

    fallbacks = {
      'validation.config_section_missing': f"Missing required section: [{kwargs.get('section', 'unknown')}]",
      'validation.required_missing': f"Missing required key: {kwargs.get('key', 'unknown')}",
      'validation.port_invalid': f"Invalid port: {kwargs.get('port', 'unknown')} (range: 1-65535)",
      'validation.path_invalid': f"Invalid path: {kwargs.get('path', 'unknown')}",
      'validation.url_invalid': f"Invalid URL: {kwargs.get('url', 'unknown')}",
      'validation.type_mismatch': f"Type mismatch for '{kwargs.get('key', 'unknown')}': expected {kwargs.get('expected', 'unknown')}, got {kwargs.get('actual', 'unknown')}",
      'validation.value_out_of_range': f"Value out of range for '{kwargs.get('key', 'unknown')}': {kwargs.get('value', 'unknown')} (range: {kwargs.get('min', 'unknown')}-{kwargs.get('max', 'unknown')})",
      'validation.invalid_format': f"Invalid format for {kwargs.get('field', 'unknown')}",
      'validation.schema_valid': "Configuration schema valid"
    }

    return fallbacks.get(msg_key, msg_key)
  
  def validate(self, config_path: Path) -> ValidationResult:
    """
    Validate configuration file.
    
    Args:
      config_path: Path to server.toml
      
    Returns:
      ValidationResult with errors and warnings
    """
    errors = []
    warnings = []
    
    try:
      with open(config_path, 'rb') as _f:
        config = tomllib.load(_f)
    except Exception as e:
      return ValidationResult(
        valid=False,
        errors=[f"Cannot parse TOML: {e}"],
        warnings=[]
      )
    
    errors.extend(self._validate_required_sections(config))
    
    errors.extend(self._validate_required_keys(config))
    
    type_errors, type_warnings = self._validate_types_and_values(config)
    errors.extend(type_errors)
    warnings.extend(type_warnings)
    
    errors.extend(self._validate_core_section(config))
    errors.extend(self._validate_plugins_section(config))
    errors.extend(self._validate_storage_section(config))
    
    path_warnings = self._validate_paths(config)
    warnings.extend(path_warnings)
    
    return ValidationResult(
      valid=len(errors) == 0,
      errors=errors,
      warnings=warnings
    )
  
  def _validate_required_sections(self, config: Dict[str, Any]) -> List[str]:
    """Validate required sections exist"""
    errors = []
    
    for section in self.REQUIRED_SECTIONS:
      if section not in config:
        msg = self._get_message('validation.config_section_missing', section=section)
        errors.append(msg)
    
    return errors
  
  def _validate_required_keys(self, config: Dict[str, Any]) -> List[str]:
    """Validate required keys exist"""
    errors = []
    
    for path, keys in self.REQUIRED_KEYS.items():
      section = config
      section_parts = path.split('.')
      
      for part in section_parts:
        if isinstance(section, dict) and part in section:
          section = section[part]
        else:
          section = {}
          break
      
      for key in keys:
        if not isinstance(section, dict) or key not in section:
          msg = self._get_message('validation.required_missing', key=f'{path}.{key}')
          errors.append(msg)
    
    return errors
  
  def _validate_meta_env(self, config: Dict[str, Any]) -> List[str]:
    """Validate meta.environment value."""
    if 'meta' not in config:
      return []
    env = config['meta'].get('environment')
    if env and env not in self.VALID_ENVIRONMENTS:
      return [f"Invalid environment: {env}. Valid: {', '.join(self.VALID_ENVIRONMENTS)}"]
    return []

  def _validate_server_fields(self, server: Dict[str, Any]) -> List[str]:
    """Validate core.server port/host/workers fields."""
    errors: list[str] = []
    port = server.get('port')
    if port is not None:
      if not isinstance(port, int):
        errors.append(self._get_message('validation.type_mismatch',
                   key='core.server.port', expected='integer', actual=type(port).__name__))
      elif not (1 <= port <= 65535):  # nosemgrep: hardcode.port_number
        errors.append(self._get_message('validation.port_invalid', port=port))
    host = server.get('host')
    if host and not isinstance(host, str):
      errors.append(self._get_message('validation.type_mismatch',
                 key='core.server.host', expected='string', actual=type(host).__name__))
    workers = server.get('workers')
    if workers is not None:
      if not isinstance(workers, int) or workers < 1:
        errors.append("core.server.workers must be a positive integer")
    return errors

  def _validate_types_and_values(self, config: Dict[str, Any]) -> tuple[List[str], List[str]]:
    """Validate data types and value ranges."""
    errors: list[str] = self._validate_meta_env(config)
    if 'core' in config and 'server' in config['core']:
      errors.extend(self._validate_server_fields(config['core']['server']))
    return errors, []
  
  @staticmethod
  def _validate_timeouts(timeouts: Dict[str, Any]) -> List[str]:
    """Validate core.timeouts sub-section."""
    errors: list[str] = []
    for key in ['request_timeout', 'startup_timeout', 'shutdown_timeout']:
      val = timeouts.get(key)
      if val is not None and (not isinstance(val, (int, float)) or val <= 0):
        errors.append(f"core.timeouts.{key} must be a positive number")
    return errors

  def _validate_cors(self, server: Dict[str, Any]) -> List[str]:
    """Validate core.server.cors_origins."""
    cors_origins = server.get('cors_origins')
    if cors_origins is None:
      return []
    if not isinstance(cors_origins, list):
      return ["core.server.cors_origins must be a list"]
    errors: list[str] = []
    for origin in cors_origins:
      if not isinstance(origin, str):
        errors.append("All CORS origins must be strings")
      elif not self._is_valid_url(origin):
        errors.append(self._get_message('validation.url_invalid', url=origin))
    return errors

  def _validate_core_section(self, config: Dict[str, Any]) -> List[str]:
    """Validate core section specifics."""
    if 'core' not in config:
      return []
    core = config['core']
    errors: list[str] = []
    if 'timeouts' in core:
      errors.extend(self._validate_timeouts(core['timeouts']))
    if 'server' in core:
      errors.extend(self._validate_cors(core['server']))
    return errors
  
  def _validate_plugins_section(self, config: Dict[str, Any]) -> List[str]:
    """Validate plugins section specifics"""
    errors: list[str] = []
    
    if 'plugins' not in config:
      return errors
    
    plugins = config['plugins']
    
    if 'models' in plugins:
      models = plugins['models']
      
      temp = models.get('temperature')
      if temp is not None:
        if not isinstance(temp, (int, float)) or not (0.0 <= temp <= 2.0):
          msg = self._get_message('validation.value_out_of_range',
                     key='plugins.models.temperature', value=temp, min='0.0', max='2.0')
          errors.append(msg)
      
      max_tokens = models.get('max_tokens')
      if max_tokens is not None:
        if not isinstance(max_tokens, int) or max_tokens <= 0:
          errors.append("plugins.models.max_tokens must be a positive integer")
    
    return errors
  
  def _validate_logging_config(self, logging_config: Dict[str, Any]) -> List[str]:
    """Validate storage.logging sub-section."""
    errors: list[str] = []
    level = logging_config.get('level')
    if level and level not in self.VALID_LOG_LEVELS:
      errors.append(f"Invalid log level: {level}. Valid: {', '.join(self.VALID_LOG_LEVELS)}")
    retention = logging_config.get('retention_days')
    if retention is not None:
      if not isinstance(retention, int) or retention <= 0:
        errors.append("storage.logging.retention_days must be a positive integer")
    return errors

  @staticmethod
  def _validate_storage_limits(storage_inner: Dict[str, Any]) -> List[str]:
    """Validate storage.storage sub-section (file size, extensions)."""
    errors: list[str] = []
    max_size = storage_inner.get('max_file_size')
    if max_size is not None:
      if not isinstance(max_size, int) or max_size <= 0:
        errors.append("storage.storage.max_file_size must be a positive integer")
    extensions = storage_inner.get('allowed_extensions')
    if extensions is not None:
      if not isinstance(extensions, list):
        errors.append("storage.storage.allowed_extensions must be a list")
      else:
        for ext in extensions:
          if not isinstance(ext, str) or not ext.startswith('.'):
            errors.append("All allowed extensions must be strings starting with '.'")
    return errors

  def _validate_storage_section(self, config: Dict[str, Any]) -> List[str]:
    """Validate storage section specifics."""
    if 'storage' not in config:
      return []
    storage = config['storage']
    errors: list[str] = []
    if 'logging' in storage:
      errors.extend(self._validate_logging_config(storage['logging']))
    if 'storage' in storage:
      errors.extend(self._validate_storage_limits(storage['storage']))
    return errors
  
  def _check_single_path(self, config: dict, path_desc: str, path_parts: list) -> Optional[str]:
    """Resolve a single nested config path and return a warning string if it does not exist."""
    section: Any = config
    for part in path_parts:
      if isinstance(section, dict) and part in section:
        section = section[part]
      else:
        return None

    if not (section and isinstance(section, str)):
      return None

    path = Path(section)
    check_path = path.parent if (path_desc.endswith('.db') or path_desc.endswith('_file')) else path
    if not check_path.exists():
      return f"Path does not exist: {section} (from {path_desc})"
    return None

  def _validate_paths(self, config: Dict[str, Any]) -> List[str]:
    """Validate that specified paths exist"""
    paths_to_check = [
      ('personality.orchestrator.modules_path', ['personality', 'orchestrator', 'modules_path']),
      ('storage.paths.logs_dir', ['storage', 'paths', 'logs_dir']),
      ('storage.database.sessions_db', ['storage', 'database', 'sessions_db']),
    ]

    warnings: list[str] = []
    for path_desc, path_parts in paths_to_check:
      warning = self._check_single_path(config, path_desc, path_parts)
      if warning:
        warnings.append(warning)
    return warnings
  
  def _is_valid_url(self, url: str) -> bool:
    """Basic URL validation"""
    url_pattern = re.compile(
      r'^https?://'
      r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|'
      r'localhost|'
      r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'
      r'(?::\d+)?'
      r'(?:/?|[/?]\S+)$', re.IGNORECASE)
    
    return bool(url_pattern.match(url))
  
  def validate_section(self, config_path: Path, section_name: str) -> ValidationResult:
    """
    Validate a specific configuration section.
    
    Args:
      config_path: Path to configuration file
      section_name: Name of section to validate
      
    Returns:
      ValidationResult for the specific section
    """
    try:
      with open(config_path, 'rb') as _f:
        config = tomllib.load(_f)
    except Exception as e:
      return ValidationResult(
        valid=False,
        errors=[f"Cannot parse TOML: {e}"],
        warnings=[],
        section=section_name
      )
    
    if section_name not in config:
      return ValidationResult(
        valid=False,
        errors=[self._get_message('validation.config_section_missing', section=section_name)],
        warnings=[],
        section=section_name
      )

    errors: list[str] = []
    warnings: list[str] = []

    if section_name == 'core':
      errors.extend(self._validate_core_section(config))
    elif section_name == 'plugins':
      errors.extend(self._validate_plugins_section(config))
    elif section_name == 'storage':
      errors.extend(self._validate_storage_section(config))
    
    return ValidationResult(
      valid=len(errors) == 0,
      errors=errors,
      warnings=warnings,
      section=section_name
    )