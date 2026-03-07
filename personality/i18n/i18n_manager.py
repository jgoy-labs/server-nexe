"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: personality/i18n/i18n_manager.py
Description: Sistema global d'internacionalització (i18n) per Nexe 0.8.

www.jgoy.net
────────────────────────────────────
"""

import json
import os
from pathlib import Path
from typing import Dict, List, Optional

import toml

__all__ = ['I18nManager']

class I18nManager:
  """Global internationalization manager for Nexe 0.8 system"""
  
  def __init__(self, config_path: Path = None, base_path: Path = None):
    """
    Initialize i18n manager.
    
    Args:
      config_path: Path to server.toml
      base_path: Base path for the system (auto-detect if None)
    """
    self.config_path = self._find_config_path(config_path)
    self.base_path = base_path or self.config_path.parent
    self.config = {}
    self.translations = {}
    _default_lang = os.getenv("NEXE_LANG", "ca-ES")
    self.current_language = _default_lang
    self.fallback_language = _default_lang
    self._translations_loaded = False
    self._load_config()
  
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
      
      loc_config = self.config.get('personality', {}).get('location', {})
      self.current_language = loc_config.get('idioma_principal', 'ca-ES')
      self.fallback_language = loc_config.get('fallback_idioma', 'ca-ES')
      
    except Exception:
      _fallback = os.getenv("NEXE_LANG", "ca-ES")
      self.current_language = _fallback
      self.fallback_language = _fallback
  
  def _ensure_translations_loaded(self) -> None:
    """Lazy load translations when first needed"""
    if self._translations_loaded:
      return
    
    self._load_translations()
    self._translations_loaded = True
  
  def _load_translations(self) -> None:
    """Load translation files"""
    try:
      loc_config = self.config.get('personality', {}).get('location', {})
      translations_path = loc_config.get('path_traduccions', 'personality/core/languages')
      
      if not Path(translations_path).is_absolute():
        translations_path = self.base_path / translations_path
      
      self._load_language_files(translations_path / self.current_language, self.current_language)
      
      if self.fallback_language != self.current_language:
        self._load_language_files(translations_path / self.fallback_language, self.fallback_language)
        
    except Exception:
      if self.current_language not in self.translations:
        self.translations[self.current_language] = {}
  
  def _load_language_files(self, lang_path: Path, language: str) -> None:
    """Load JSON files for a specific language"""
    if language not in self.translations:
      self.translations[language] = {}
    
    core_messages = lang_path / 'messages.json'
    if core_messages.exists():
      try:
        with open(core_messages, 'r', encoding='utf-8') as f:
          data = json.load(f)
          if '_meta' in data:
            del data['_meta']
          self.translations[language].update(data)
      except (IOError, KeyError):
        pass
    
    modules_base = self.base_path / 'plugins' / 'moduls'
    if modules_base.exists():
      self._load_module_translations(modules_base, language)
    
    additional_paths = self.config.get('personality', {}).get('orchestrator', {}).get('additional_paths', {}).get('paths', [])
    for path_str in additional_paths:
      additional_path = self.base_path / path_str
      if additional_path.exists():
        self._load_module_translations(additional_path, language)
  
  def _load_module_translations(self, modules_path: Path, language: str) -> None:
    """Load translations from module directories"""
    try:
      for module_dir in modules_path.iterdir():
        if not module_dir.is_dir():
          continue
        
        module_messages = module_dir / 'location' / 'languages' / language / 'messages.json'
        if module_messages.exists():
          try:
            with open(module_messages, 'r', encoding='utf-8') as f:
              module_data = json.load(f)
              if '_meta' in module_data:
                del module_data['_meta']
              module_name = module_dir.name
              if module_name not in self.translations[language]:
                self.translations[language][module_name] = {}
              self.translations[language][module_name].update(module_data)
          except (IOError, KeyError):
            pass
    except (IOError, KeyError):
      pass
  
  def t(self, key: str, **kwargs) -> str:
    """
    Translate a key with optional parameters.
    
    Args:
      key: Translation key in dot format (module_manager.init.started)
      **kwargs: Parameters for interpolation
      
    Returns:
      Translated text or key if not found
    """
    self._ensure_translations_loaded()
    
    parts = key.split('.')
    
    translation = self._get_nested_value(
      self.translations.get(self.current_language, {}), 
      parts
    )
    
    if translation is None and self.fallback_language != self.current_language:
      translation = self._get_nested_value(
        self.translations.get(self.fallback_language, {}), 
        parts
      )
    
    if translation is None:
      translation = key
    
    try:
      return translation.format(**kwargs)
    except (KeyError, ValueError):
      return translation
  
  def _get_nested_value(self, data: Dict, keys: List[str]) -> Optional[str]:
    """Get nested value from dictionary"""
    current = data
    for key in keys:
      if isinstance(current, dict) and key in current:
        current = current[key]
      else:
        return None
    return current if isinstance(current, str) else None
  
  def reload_translations(self) -> bool:
    """Reload all translation files"""
    try:
      self._load_config()
      self._translations_loaded = False
      return True
    except Exception:
      return False
  
  def get_available_languages(self) -> List[str]:
    """Get list of available languages"""
    self._ensure_translations_loaded()
    return list(self.translations.keys())
  
  def set_language(self, language: str) -> bool:
    """Change current language"""
    self._ensure_translations_loaded()
    if language in self.translations:
      self.current_language = language
      return True
    return False
  
  def has_translation(self, key: str) -> bool:
    """Check if a translation key exists"""
    self._ensure_translations_loaded()
    parts = key.split('.')
    
    if self._get_nested_value(self.translations.get(self.current_language, {}), parts):
      return True
    
    if self.fallback_language != self.current_language:
      return bool(self._get_nested_value(self.translations.get(self.fallback_language, {}), parts))
    
    return False
  
  def get_translation_stats(self) -> Dict[str, int]:
    """Get translation statistics"""
    self._ensure_translations_loaded()
    
    def count_keys(data, prefix=""):
      count = 0
      for key, value in data.items():
        if isinstance(value, dict):
          count += count_keys(value, f"{prefix}{key}.")
        elif isinstance(value, str):
          count += 1
      return count
    
    stats = {}
    for lang, data in self.translations.items():
      stats[lang] = count_keys(data)
    
    return stats