"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: personality/i18n/modular_i18n.py
Description: Sistema modular d'internacionalització. Auto-descobreix messages_*.json per

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import json
from pathlib import Path
from typing import Dict, List, Optional
import toml
import logging

logger = logging.getLogger(__name__)

__all__ = ['ModularI18nManager']

class ModularI18nManager:
  """Gestor d'internacionalització modular per Nexe 0.8"""
  
  def __init__(self, config_path: Path = None, base_path: Path = None):
    """
    Initialize modular i18n manager.
    
    Args:
      config_path: Path to server.toml
      base_path: Base path for scanning (project root)
    """
    self.config_path = self._find_config_path(config_path)
    self.base_path = base_path or self.config_path.parent.parent
    self.config = {}
    self.translations = {}
    self.current_language = "en-US"
    self.fallback_language = "en-US"
    self._load_config()
    self._discover_and_load_translations()
  
  def _find_config_path(self, config_path: Optional[Path]) -> Path:
    """Find configuration file using centralized search from core.config."""
    if config_path and config_path.exists():
      return config_path
    from core.config import find_config_path as core_find_config_path
    return core_find_config_path() or Path("personality/server.toml")
  
  def _load_config(self) -> None:
    """Load language configuration from server.toml"""
    try:
      if self.config_path.exists():
        with open(self.config_path, 'r', encoding='utf-8') as f:
          self.config = toml.load(f)

      # Read from personality.i18n section (correct path)
      i18n_config = self.config.get('personality', {}).get('i18n', {})
      self.current_language = i18n_config.get('default_language', 'en-US')
      self.fallback_language = i18n_config.get('fallback_language', 'en-US')

    except Exception:
      self.current_language = "en-US"
      self.fallback_language = "en-US"
  
  def _discover_and_load_translations(self) -> None:
    """Discover and load all translation files"""
    logger.info("Descobrint traduccions per %s...", self.current_language)

    search_patterns = [
      f"**/languages/{self.current_language}/messages_*.json",
      f"**/**/languages/{self.current_language}/messages_*.json",
    ]

    found_files = []
    for pattern in search_patterns:
      files = list(self.base_path.glob(pattern))
      found_files.extend(files)

    found_files = list(set(found_files))

    if not found_files:
      logger.warning("Cap fitxer de traduccions trobat per %s", self.current_language)
      return

    loaded_count = 0
    for file_path in found_files:
      if self._load_translation_file(file_path):
        loaded_count += 1

    logger.info("Carregades %d/%d traduccions", loaded_count, len(found_files))

    if self.current_language in self.translations:
      components = list(self.translations[self.current_language].keys())
      logger.debug("Components amb traduccions: %s", ', '.join(components))
  
  def _load_translation_file(self, file_path: Path) -> bool:
    """Load a specific translation file"""
    try:
      with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
      
      filename = file_path.stem
      if filename.startswith('messages_'):
        prefix = filename[9:]
      else:
        prefix = filename
      
      if self.current_language not in self.translations:
        self.translations[self.current_language] = {}
      
      if '_meta' in data:
        del data['_meta']
      
      if prefix in data:
        self.translations[self.current_language][prefix] = data[prefix]
      else:
        self.translations[self.current_language][prefix] = data

      logger.debug(" %s : %s", prefix, file_path.name)
      return True

    except Exception as e:
      logger.error("Error carregant %s: %s", file_path, e)
      return False
  
  def t(self, key: str, **kwargs) -> str:
    """
    Translate a key with format: component.section.key
    
    Args:
      key: Translation key (server_core.startup.ready)
      **kwargs: Parameters for interpolation
      
    Returns:
      Translated text or key if not found
    """
    parts = key.split('.')
    if len(parts) < 2:
      return key
    
    component = parts[0]
    message_path = parts[1:]
    
    translation = self._get_translation(self.current_language, component, message_path)
    
    if translation is None and self.fallback_language != self.current_language:
      translation = self._get_translation(self.fallback_language, component, message_path)
    
    if translation is None:
      return key
    
    try:
      return translation.format(**kwargs)
    except (KeyError, ValueError):
      return translation
  
  def _get_translation(self, language: str, component: str, path: List[str]) -> Optional[str]:
    """Search for a specific translation"""
    if language not in self.translations:
      return None
    
    if component not in self.translations[language]:
      return None
    
    current = self.translations[language][component]
    
    for key in path:
      if isinstance(current, dict) and key in current:
        current = current[key]
      else:
        return None
    
    return current if isinstance(current, str) else None
  
  def register_component_translations(self, component: str, translations: Dict) -> None:
    """Register translations for a specific component"""
    if self.current_language not in self.translations:
      self.translations[self.current_language] = {}

    self.translations[self.current_language][component] = translations
    logger.info("Traduccions registrades per %s", component)
  
  def get_available_components(self) -> List[str]:
    """Return list of components with translations"""
    if self.current_language in self.translations:
      return list(self.translations[self.current_language].keys())
    return []
  
  def reload_translations(self) -> bool:
    """Reload all translation files"""
    try:
      self.translations.clear()
      self._load_config()
      self._discover_and_load_translations()
      return True
    except Exception:
      return False
  
  def has_translation(self, key: str) -> bool:
    """Check if a translation key exists"""
    parts = key.split('.')
    if len(parts) < 2:
      return False
    
    component = parts[0]
    message_path = parts[1:]
    
    if self._get_translation(self.current_language, component, message_path):
      return True
    
    if self.fallback_language != self.current_language:
      return bool(self._get_translation(self.fallback_language, component, message_path))
    
    return False
  
  def get_stats(self) -> Dict:
    """Translation system statistics"""
    def count_keys(data, prefix=""):
      count = 0
      for key, value in data.items():
        if isinstance(value, dict):
          count += count_keys(value, f"{prefix}{key}.")
        elif isinstance(value, str):
          count += 1
      return count
    
    stats = {
      'current_language': self.current_language,
      'fallback_language': self.fallback_language,
      'components': len(self.get_available_components()),
      'available_components': self.get_available_components(),
      'total_keys': {}
    }
    
    for lang, components in self.translations.items():
      stats['total_keys'][lang] = {}
      for component, data in components.items():
        stats['total_keys'][lang][component] = count_keys(data)
    
    return stats