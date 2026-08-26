"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: personality/i18n/i18n_manager.py
Description: Global internationalization (i18n) system for server-nexe.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import logging

import tomllib  # uiri toml moria abans de [personality.i18n] al server.toml real (#834)

logger = logging.getLogger(__name__)

__all__ = ['I18nManager']

class I18nManager:
  """Global internationalization manager for server-nexe system"""
  
  def __init__(self, config_path: Optional[Path] = None, base_path: Optional[Path] = None):
    """
    Initialize i18n manager.
    
    Args:
      config_path: Path to server.toml
      base_path: Base path for the system (auto-detect if None)
    """
    self.config_path = self._find_config_path(config_path)
    self.base_path = base_path or self.config_path.parent
    self.config: Dict[str, Any] = {}
    self.translations: Dict[str, Any] = {}
    _default_lang = os.getenv("NEXE_LANG", "en-US")
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
  
  def _configured_additional_paths(self) -> list:
    """The orchestrator's additional_paths, accepting both shapes it comes in.

    server.toml declares `additional_paths = ["personality", "memory"]` — a
    LIST — while this module assumed the `{paths = [...]}` table shape and did
    `.get('paths', [])` on it. That AttributeError was swallowed whole by the
    `except Exception` in _load_translations, taking the entire module-catalog
    scan down with it: a third, silent cause of #920. core/modules/path_discovery.py
    already handles both shapes (:197-205); this is the same handling.
    """
    configured = self.config.get('personality', {}).get('orchestrator', {}).get('additional_paths', [])
    if isinstance(configured, dict):
      configured = configured.get('paths', [])
    return configured if isinstance(configured, list) else []

  def _resolve_scan_base(self, relative: str) -> Path:
    """Resolve a catalog directory, honouring base_path before the repo root.

    base_path comes from the caller and is authoritative: tests and embedders
    pass their own tree and must keep getting it. But ModuleManager passes the
    directory holding server.toml (personality/), and the config paths
    ('personality/languages', 'plugins', 'memory') are written against the REPO
    ROOT — under personality/ they resolve to personality/personality/languages
    and friends, none of which exist. That is one half of #920.

    So: caller's base_path first; only when nothing is there, the canonical repo
    root that core/paths already computes.
    """
    from_base = self.base_path / relative
    if from_base.is_dir():
      return from_base

    try:
      from core.paths.detection import get_repo_root
      repo_root = get_repo_root()
    except Exception:
      return from_base

    # Only fall back for a base_path that lives INSIDE the repo (personality/,
    # the real caller). A base_path pointing elsewhere — a tmp_path in a test, an
    # embedder's own tree — is the caller's own world and must stay isolated:
    # reaching into the repo from there would load catalogs nobody asked for.
    try:
      self.base_path.resolve().relative_to(repo_root.resolve())
    except ValueError:
      return from_base
    return repo_root / relative

  def _load_config(self) -> None:
    """Load language configuration from server.toml.

    #931: used to read personality.location.idioma_principal/fallback_idioma,
    a section that does not exist in the real server.toml — current_language
    fell to the literal 'ca-ES' default on every real install, regardless of
    what the user configured. ModularI18nManager already reads the section
    that is actually there (personality.i18n.default_language/
    fallback_language); this now reads the same one, so both managers agree.

    NEXE_LANG (set by the launcher / Tauri parent as an explicit runtime
    override — see plugins/web_ui_module/api/routes_auth.py) takes priority
    over server.toml when present, same as __init__ already assumed before
    this method silently overwrote it.
    """
    try:
      if self.config_path.exists():
        with open(self.config_path, 'rb') as f:
          self.config = tomllib.load(f)

      if os.getenv("NEXE_LANG"):
        return  # explicit override already set in __init__; server.toml yields to it

      i18n_config = self.config.get('personality', {}).get('i18n', {})
      self.current_language = i18n_config.get('default_language', 'en-US')
      self.fallback_language = i18n_config.get('fallback_language', 'en-US')

    except Exception:
      _fallback = os.getenv("NEXE_LANG", "en-US")
      self.current_language = _fallback
      self.fallback_language = _fallback
  
  def _ensure_translations_loaded(self) -> None:
    """Lazy load translations when first needed"""
    if self._translations_loaded:
      return
    
    self._load_translations()
    self._translations_loaded = True
  
  def _load_translations(self) -> None:
    """Load translation files.

    #931 (continued): same shape as _load_config() — this used to read
    personality.location.path_traduccions, a key that does not exist in the
    real server.toml either. Harmless in production only by accident: the
    hardcoded default here ('personality/languages') happens to equal
    personality.i18n.translations_path's real value, and ModuleManager's
    base_path (personality/) makes the FIRST resolution attempt miss too,
    falling through to _resolve_scan_base's repo-root fallback — which
    silently ignores whatever this key actually said. A test base_path
    outside the repo (tmp_path) gets no such fallback and exposes it.
    """
    try:
      i18n_config = self.config.get('personality', {}).get('i18n', {})
      translations_path = i18n_config.get('translations_path', 'personality/languages')
      
      if not Path(translations_path).is_absolute():
        translations_path = self._resolve_scan_base(translations_path)
      
      self._load_language_files(translations_path / self.current_language, self.current_language)
      
      if self.fallback_language != self.current_language:
        self._load_language_files(translations_path / self.fallback_language, self.fallback_language)
        
    except Exception:
      if self.current_language not in self.translations:
        self.translations[self.current_language] = {}
  
  def _catalog_is_for(self, catalog: Path, data: dict, language: str) -> bool:
    """Whether a catalog may be served for ``language``.

    A catalog that DECLARES ``_meta.language`` and declares a different one is a
    mislabelled copy: serving it would hand the user a language they did not ask
    for. This started as the guard for core/modules/languages/{en-US,es-ES}/,
    which were byte-for-byte copies of the ca-ES catalogs with
    `_meta.language: "ca-ES"` inside. Those were really translated on 2026-08-26
    (#960), so the guard no longer refuses anything in-tree — it stays as the
    standing rule for the next copy-pasted catalog, exercised by a synthetic
    test rather than by real mislabelled files.

    Declaring NOTHING is not the same as declaring the wrong thing: six catalogs
    in the repo ship no ``_meta.language`` and keep loading exactly as today.
    """
    declared = data.get('_meta', {}).get('language') if isinstance(data.get('_meta'), dict) else None
    if declared is None or declared == language:
      return True
    logger.warning(
      "i18n: refusing catalog %s — it declares language %r but sits in the %r "
      "directory; falling back rather than serving the wrong language",
      catalog, declared, language,
    )
    return False

  def _load_language_files(self, lang_path: Path, language: str) -> None:
    """Load JSON files for a specific language.

    Loads the legacy flat ``messages.json`` (if present) plus the real
    per-component ``messages_*.json`` catalog files. Each ``messages_<comp>.json``
    is nested under its component prefix (``core_metrics``, ``core_events`` …) so
    keys resolve as ``component.section.key``, matching ModularI18nManager.
    """
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

    if lang_path.exists():
      for comp_file in sorted(lang_path.glob('messages_*.json')):
        try:
          with open(comp_file, 'r', encoding='utf-8') as f:
            comp_data = json.load(f)
          if not self._catalog_is_for(comp_file, comp_data, language):
            continue
          if '_meta' in comp_data:
            del comp_data['_meta']
          component = comp_file.stem[len('messages_'):]
          self.translations[language][component] = comp_data
        except (IOError, KeyError, ValueError):
          pass

    # #920 — these used to hang off base_path, which ModuleManager sets to the
    # directory holding server.toml (personality/), so they resolved to
    # personality/plugins, personality/personality and personality/memory: none
    # of them exist. Anchored at the repo root, the way ModularI18nManager is
    # given project_root.
    # #957: 'core' used to be hardcoded here (#920's immediate fix, 23/08) because
    # server.toml's additional_paths was not updated when the module system moved
    # down to core/modules/ on 22/08. Now declared in server.toml like the rest.
    for path_str in ('plugins', *self._configured_additional_paths()):
      base_dir = self._resolve_scan_base(path_str)
      if base_dir.is_dir():
        self._load_module_translations(base_dir, language)
  
  def _load_module_translations(self, modules_path: Path, language: str) -> None:
    """Load the translation catalogs the modules under ``modules_path`` ship.

    #920 — the layout this used to look for (``<module>/location/languages/
    <lang>/messages.json``) never existed: there is no literal ``location/``
    directory anywhere in the repo. The real layout is flat and per component,
    the same one ``_load_language_files`` and ModularI18nManager already read:

        <module>/languages/<lang>/messages_<component>.json

    The component name comes from the file name, so keys resolve as
    ``component.section.key`` — the dotted format ``t()`` documents.
    """
    try:
      for module_dir in sorted(modules_path.iterdir()):
        if not module_dir.is_dir():
          continue

        catalog_dir = module_dir / 'languages' / language
        if not catalog_dir.is_dir():
          continue

        for catalog in sorted(catalog_dir.glob('messages_*.json')):
          component = catalog.stem[len('messages_'):]
          try:
            with open(catalog, 'r', encoding='utf-8') as f:
              module_data = json.load(f)
          except (IOError, KeyError, ValueError) as exc:
            # Not silent: a malformed catalog used to leave the user with
            # English and no way to know why (#890 — ask what happens when it
            # breaks, not only whether it raises). Not widened to
            # `except Exception`: a bug in our own code must still surface.
            logger.warning("i18n: could not load catalog %s: %s", catalog, exc)
            continue

          if not self._catalog_is_for(catalog, module_data, language):
            continue
          if '_meta' in module_data:
            del module_data['_meta']
          # The loaders unwrap a top-level key equal to the component, if present.
          if component in module_data and isinstance(module_data[component], dict):
            module_data = module_data[component]

          if component not in self.translations[language]:
            self.translations[language][component] = {}
          self.translations[language][component].update(module_data)
    except (IOError, KeyError, OSError) as exc:
      logger.warning("i18n: could not scan modules under %s: %s", modules_path, exc)
  
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
      self.translations.clear()
      # B134: clear before re-loading so keys removed from the files do not
      # survive in memory (parity with ModularI18nManager.reload_translations).
      # _load_config() does not touch self.translations and the catalog is
      # re-read lazily via _ensure_translations_loaded, so clearing here is safe.
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