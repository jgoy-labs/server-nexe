"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: personality/module_manager/path_discovery.py
Description: Nexe module path discovery. Scans core/tools per layer,

www.jgoy.net
────────────────────────────────────
"""

from pathlib import Path
from typing import List, Set, Dict, Any
import json

import logging
logger = logging.getLogger(__name__)
LOGGER_AVAILABLE = False

class PathDiscovery:
  """
  Module path discovery for Nexe 0.8.

  Searches for modules in:
  - Known paths (plugins/moduls, memory/modules, etc.)
  - Any first-level folder with 'modul' in the name (DEV MODE ONLY)
  - Explicitly configured paths

  Security Modes:
  - strict=True (PRODUCTION): Only known paths + explicitly configured
  - strict=False (DEV): Also auto-discovers folders with 'modul' in name
  """

  def __init__(self, config: Dict[str, Any] = None, i18n_manager=None, strict: bool = None):
    """
    Initialize path discovery.

    Args:
      config: System configuration dictionary
      i18n_manager: Optional I18nManager for translations
      strict: Force strict mode (True=production, False=dev).
              If None, reads from config or defaults to True (safe default)
    """
    self.config = config or {}
    self.i18n = i18n_manager
    self.base_path = Path(".")
    self._discovered_paths: Set[Path] = set()
    self._module_locations: Dict[str, Path] = {}

    # Determine strict mode (production vs dev)
    if strict is not None:
      self.strict_mode = strict
    else:
      # Read from config, default to True (production/safe)
      env_config = self.config.get('core', {}).get('environment', {})
      mode = env_config.get('mode', 'production')
      self.strict_mode = mode != 'development'

    if not self.strict_mode:
      logger.warning(self._get_message('path_discovery.dev_mode'))
    
    self.known_paths = [
      "plugins/core",
      "plugins/tools",
      "storage/core",
      "storage/tools",
      "memory/core",
      "memory/tools",
      "core/core",
      "core/tools",
      "personality/core",
      "personality/tools"
    ]
    
    self.module_patterns = ['modul', 'module', 'mods']
    
    self.ignore_patterns = ['.', '_', '__pycache__', 'node_modules', 
                'venv', '.git', 'dist', 'build']
  
  def _get_message(self, key: str, **kwargs) -> str:
    """Get translated message or fallback"""
    if self.i18n:
      return self.i18n.t(key, **kwargs)
    
    fallbacks = {
      'path_discovery.dev_mode': "PathDiscovery in DEV MODE - auto-discovery enabled",
      'path_discovery.strict_mode_skip': "Strict mode: skipping auto-discovery",
      'path_discovery.scanning': "Scanning paths for modules...",
      'path_discovery.path_added': f"Path added: {kwargs.get('path', 'unknown')}",
      'path_discovery.module_found': f"Module found: '{kwargs.get('name', 'unknown')}' at {kwargs.get('path', 'unknown')}",
      'path_discovery.auto_discovered': f"Auto-discovered: {kwargs.get('path', 'unknown')}",
      'path_discovery.cache_saved': f"Path cache saved to {kwargs.get('file', 'unknown')}",
      'path_discovery.cache_loaded': f"Path cache loaded from {kwargs.get('file', 'unknown')}",
      'path_discovery.permission_denied': f"Permission denied scanning: {kwargs.get('path', 'unknown')}",
      'path_discovery.max_dirs_reached': f"Maximum directory limit reached: {kwargs.get('max', 'unknown')}",
      'path_discovery.paths_discovered': f"Discovered {kwargs.get('count', 0)} module paths",
      'path_discovery.debug.path_item': f" - {kwargs.get('path', 'unknown')}",
      'path_discovery.info.modules_found': f"Found {kwargs.get('count', 0)} modules",
      'path_discovery.errors.cache_save_failed': f"Failed to save cache: {kwargs.get('error', 'unknown')}",
      'path_discovery.errors.cache_load_failed': f"Failed to load cache: {kwargs.get('error', 'unknown')}"
    }
    
    return fallbacks.get(key, key)
  
  def discover_all_paths(self) -> List[Path]:
    """
    Discover all paths that may contain modules.

    In strict mode (production), only uses known paths and configured paths.
    In dev mode, also auto-discovers folders with 'modul' in name.

    Returns:
      List of resolved paths
    """
    self._discovered_paths.clear()

    self._add_known_paths()

    # Auto-discovery only in dev mode (security hardening)
    if not self.strict_mode:
      self._auto_discover_paths()
    else:
      logger.debug(self._get_message('path_discovery.strict_mode_skip'))

    self._add_configured_paths()
    
    paths = list(self._discovered_paths)
    known_path_strs = [str(self.base_path / kp) for kp in self.known_paths]
    paths.sort(key=lambda p: (
      str(p) not in known_path_strs,
      str(p)
    ))
    
    if LOGGER_AVAILABLE:
      msg = self._get_message('path_discovery.paths_discovered', count=len(paths))
      logger.info(msg, component="path_discovery", count=len(paths))
      for path in paths:
        msg = self._get_message('path_discovery.debug.path_item', path=str(path))
        logger.debug(msg, component="path_discovery")
    
    return paths
  
  def _add_known_paths(self) -> None:
    """Add known paths if they exist"""
    for path_str in self.known_paths:
      path = self.base_path / path_str
      if path.exists() and path.is_dir():
        self._discovered_paths.add(path.resolve())
        if LOGGER_AVAILABLE:
          msg = self._get_message('path_discovery.path_added', path=str(path))
          logger.debug(msg, component="path_discovery")
  
  def _auto_discover_paths(self) -> None:
    """Auto-discovery in first-level folders"""
    try:
      MAX_DIRS = 100
      dir_count = 0
      for first_level in self.base_path.iterdir():
        if first_level.name.startswith(tuple(self.ignore_patterns)):
          continue
          
        if not first_level.is_dir():
          continue
        
        if dir_count >= MAX_DIRS:
          if LOGGER_AVAILABLE:
            msg = self._get_message('path_discovery.max_dirs_reached', max=MAX_DIRS)
            logger.warning(msg, component="path_discovery")
          break
        dir_count += 1
        
        subdir_count = 0
        for subdir in first_level.iterdir():
          if subdir_count >= 50:
            break
          subdir_count += 1
          if not subdir.is_dir():
            continue
          
          if any(pattern in subdir.name.lower() for pattern in self.module_patterns):
            resolved = subdir.resolve()
            if resolved not in self._discovered_paths:
              self._discovered_paths.add(resolved)
              if LOGGER_AVAILABLE:
                msg = self._get_message('path_discovery.auto_discovered', path=str(subdir))
                logger.debug(msg, component="path_discovery")
    except PermissionError as e:
      if LOGGER_AVAILABLE:
        msg = self._get_message('path_discovery.permission_denied', path=str(e))
        logger.warning(msg, component="path_discovery")
  
  def _add_configured_paths(self) -> None:
    """Add paths from configuration"""
    if not self.config:
      return

    orchestrator_config = self.config.get('personality', {}).get('orchestrator', {})
    if not isinstance(orchestrator_config, dict):
      orchestrator_config = {}

    modules_path = orchestrator_config.get('modules_path')
    if modules_path:
      path = self.base_path / modules_path
      if path.exists() and path.is_dir():
        self._discovered_paths.add(path.resolve())
        if LOGGER_AVAILABLE:
          msg = self._get_message('path_discovery.path_added', path=str(path))
          logger.debug(msg, component="path_discovery")

    add_paths_cfg = orchestrator_config.get('additional_paths', {})
    if not isinstance(add_paths_cfg, dict):
      add_paths_cfg = {}
      
    additional_paths = add_paths_cfg.get('paths', [])
    if not isinstance(additional_paths, list):
      additional_paths = []
      
    for path_str in additional_paths:
      path = self.base_path / path_str
      if path.exists() and path.is_dir():
        self._discovered_paths.add(path.resolve())
        if LOGGER_AVAILABLE:
          msg = self._get_message('path_discovery.path_added', path=str(path))
          logger.debug(msg, component="path_discovery")
  
  def scan_for_modules(self, module_paths: List[Path]) -> Dict[str, Path]:
    """
    Scan given paths for modules.
    
    Args:
      module_paths: List of paths to scan
      
    Returns:
      Dict with module_name -> module_path
    """
    self._module_locations.clear()
    
    for path in module_paths:
      if not path.exists():
        continue
        
      modules = self._scan_single_path(path)
      self._module_locations.update(modules)
    
    if LOGGER_AVAILABLE:
      msg = self._get_message('path_discovery.info.modules_found',
                  count=len(self._module_locations))
      logger.info(msg, component="path_discovery")
    
    return self._module_locations.copy()
  
  def _scan_single_path(self, path: Path) -> Dict[str, Path]:
    """
    Scan a specific path for modules.
    
    Args:
      path: Path to scan
      
    Returns:
      Dict with module_name -> module_path
    """
    modules = {}
    
    try:
      for item in path.iterdir():
        if not item.is_dir():
          continue
          
        if item.name.startswith(tuple(self.ignore_patterns)):
          continue
        
        if self._is_module_directory(item):
          module_name = item.name
          modules[module_name] = item.resolve()
          if LOGGER_AVAILABLE:
            msg = self._get_message('path_discovery.module_found', 
                       name=module_name, path=str(item))
            logger.debug(msg, component="path_discovery")
            
    except PermissionError as e:
      if LOGGER_AVAILABLE:
        msg = self._get_message('path_discovery.permission_denied', path=str(path))
        logger.warning(msg, component="path_discovery")
    
    return modules
  
  def _is_module_directory(self, path: Path) -> bool:
    """
    Determine if a directory is a module.

    A TRUE module MUST have one of:
    - manifest.toml
    - manifest.py

    Args:
      path: Directory path

    Returns:
      True if it's a valid module (has manifest)
    """
    manifest_indicators = [
      'manifest.toml',
      'manifest.py',
    ]

    for pattern in manifest_indicators:
      if list(path.glob(pattern)):
        return True

    return False
  
  def find_module_path(self, module_name: str) -> Path:
    """
    Find the path of a specific module.
    
    Args:
      module_name: Module name
      
    Returns:
      Module path or None
    """
    if module_name in self._module_locations:
      return self._module_locations[module_name]
    
    paths = self.discover_all_paths()
    modules = self.scan_for_modules(paths)
    
    return modules.get(module_name)
  
  def get_stats(self) -> Dict[str, Any]:
    """Return discovery statistics"""
    return {
      'paths_discovered': len(self._discovered_paths),
      'modules_found': len(self._module_locations),
      'paths': [str(p) for p in self._discovered_paths],
      'modules': list(self._module_locations.keys())
    }
  
  def save_cache(self, cache_file: Path = None) -> None:
    """
    Save cache of discovered paths and modules.
    
    Args:
      cache_file: Cache file path
    """
    if cache_file is None:
      cache_file = Path("personality/.module_cache.json")
    
    cache_data = {
      'paths': [str(p) for p in self._discovered_paths],
      'modules': {k: str(v) for k, v in self._module_locations.items()}
    }
    
    try:
      cache_file.parent.mkdir(parents=True, exist_ok=True)
      with open(cache_file, 'w') as f:
        json.dump(cache_data, f, indent=2)
      
      if LOGGER_AVAILABLE:
        msg = self._get_message('path_discovery.cache_saved', file=str(cache_file))
        logger.debug(msg, component="path_discovery")
    except Exception as e:
      if LOGGER_AVAILABLE:
        msg = self._get_message('path_discovery.errors.cache_save_failed', error=str(e))
        logger.warning(msg, component="path_discovery")
  
  def load_cache(self, cache_file: Path = None) -> bool:
    """
    Load cache of paths and modules.
    
    Args:
      cache_file: Cache file path
      
    Returns:
      True if loaded successfully
    """
    if cache_file is None:
      cache_file = Path("personality/.module_cache.json")
    
    if not cache_file.exists():
      return False
    
    try:
      with open(cache_file, 'r') as f:
        cache_data = json.load(f)
      
      self._discovered_paths = {Path(p) for p in cache_data.get('paths', [])}
      self._module_locations = {
        k: Path(v) for k, v in cache_data.get('modules', {}).items()
      }
      
      if LOGGER_AVAILABLE:
        msg = self._get_message('path_discovery.cache_loaded', file=str(cache_file))
        logger.debug(msg, component="path_discovery")
      
      return True
      
    except Exception as e:
      if LOGGER_AVAILABLE:
        msg = self._get_message('path_discovery.errors.cache_load_failed', error=str(e))
        logger.warning(msg, component="path_discovery")
      return False
