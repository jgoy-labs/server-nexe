"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/config.py
Description: Unified configuration management for Nexe server.
             Single source of truth for all config loading.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import copy
from pathlib import Path
from typing import Dict, Any, Optional
import tomllib
import toml
import logging
import os

logger = logging.getLogger(__name__)

# Default configuration
DEFAULT_CONFIG = {
    'core': {
        'server': {
            'host': '127.0.0.1',
            'port': 9119,
            'cors_origins': ['http://localhost:3000']
        },
        'environment': {
            'mode': 'production'  # 'production' or 'development'
        }
    },
    'security': {
        'encryption': {
            'enabled': False,
            'warn_unencrypted': True
        }
    }
}

# Standard search paths for config
CONFIG_SEARCH_PATHS = [
    "server.toml",
    "personality/server.toml",
    "config/server.toml"
]


def find_config_path(project_root: Optional[Path] = None) -> Optional[Path]:
    """
    Find the configuration file path.

    Args:
        project_root: Optional project root directory

    Returns:
        Path to config file or None if not found
    """
    base = Path(project_root) if project_root else Path.cwd()

    for config_rel in CONFIG_SEARCH_PATHS:
        config_path = base / config_rel
        if config_path.exists():
            return config_path.resolve()

    return None


def load_config(
    project_root: Optional[Path] = None,
    i18n=None,
    config_path: Optional[Path] = None
) -> Dict[str, Any]:
    """
    Load configuration from server.toml.

    This is the UNIFIED config loading function. Use this instead of
    loading config directly from files.

    Args:
        project_root: Path to project root directory
        i18n: I18n manager for translated messages (optional)
        config_path: Direct path to config file (overrides search)

    Returns:
        Dict with configuration data (merged with defaults)
    """
    # Find config file
    if config_path and config_path.exists():
        found_path = config_path
    else:
        found_path = find_config_path(project_root)

    if not found_path:
        if i18n:
            logger.warning(i18n.t("server_core.startup.config_not_found"))
        else:
            logger.warning("No config file found, using defaults")
        return copy.deepcopy(DEFAULT_CONFIG)

    # Load config
    try:
        if i18n:
            logger.info(i18n.t("server_core.startup.loading_config", path=str(found_path)))
        else:
            logger.info("Loading config from: %s", found_path)

        with open(found_path, 'rb') as f:
            config = tomllib.load(f)

        # Merge with defaults (config overrides defaults)
        merged = _deep_merge(copy.deepcopy(DEFAULT_CONFIG), config)

        if i18n:
            logger.info(i18n.t("server_core.startup.config_loaded"))
        else:
            logger.info("Config loaded successfully")

        return merged

    except Exception as e:
        if i18n:
            logger.error(i18n.t("server_core.startup.config_error",
                                path=str(found_path), error=str(e)))
        else:
            logger.error("Error loading config from %s: %s", found_path, e)
        return copy.deepcopy(DEFAULT_CONFIG)


def save_config(config: Dict[str, Any], config_path: Path) -> bool:
    """
    Save configuration to a TOML file.

    Args:
        config: Configuration dictionary to save
        config_path: Path to save config file

    Returns:
        True if saved successfully
    """
    try:
        with open(config_path, 'w', encoding='utf-8') as f:
            toml.dump(config, f)
        logger.info("Config saved to %s", config_path)
        return True
    except Exception as e:
        logger.error("Error saving config to %s: %s", config_path, e)
        return False


def get_environment_mode(config: Dict[str, Any]) -> str:
    """
    Get the environment mode from config.

    Args:
        config: Configuration dictionary

    Returns:
        'production' or 'development'
    """
    # Check environment variable first
    env_mode = os.environ.get('NEXE_ENV', os.environ.get('ENV'))
    if env_mode in ('production', 'development'):
        return env_mode

    # Then check config
    return config.get('core', {}).get('environment', {}).get('mode', 'production')


def is_production(config: Dict[str, Any]) -> bool:
    """Check if running in production mode."""
    return get_environment_mode(config) == 'production'


def is_development(config: Dict[str, Any]) -> bool:
    """Check if running in development mode."""
    return get_environment_mode(config) == 'development'


def _deep_merge(base: Dict, override: Dict) -> Dict:
    """
    Deep merge two dictionaries.

    Args:
        base: Base dictionary (will be modified)
        override: Dictionary with overriding values

    Returns:
        Merged dictionary
    """
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


# Singleton config instance
_config: Optional[Dict[str, Any]] = None
_config_path: Optional[Path] = None


def get_config(reload: bool = False) -> Dict[str, Any]:
    """
    Get the global configuration singleton.

    Args:
        reload: Force reload from file

    Returns:
        Configuration dictionary
    """
    global _config, _config_path

    if _config is None or reload:
        _config_path = find_config_path()
        _config = load_config(config_path=_config_path)

    return _config


def get_config_path() -> Optional[Path]:
    """Get the path to the loaded config file."""
    global _config_path
    if _config_path is None:
        get_config()  # Initialize
    return _config_path


def reset_config() -> None:
    """Reset the config singleton. Use only in tests."""
    global _config, _config_path
    _config = None
    _config_path = None


def get_module_allowlist(config: Dict[str, Any] = None) -> Optional[set]:
    """
    Single source of truth for module allowlist.

    Reads NEXE_APPROVED_MODULES env var and validates against environment mode.
    In production, the allowlist is required.

    Args:
        config: Optional configuration dictionary for mode detection

    Returns:
        Set of approved module names, or None if no allowlist is active

    Raises:
        ValueError: If in production mode without NEXE_APPROVED_MODULES
    """
    core_env = os.getenv("NEXE_ENV", "development").lower()
    config_mode = ""
    if config:
        config_mode = config.get("core", {}).get("environment", {}).get("mode", "")
    is_prod = core_env == "production" or config_mode == "production"

    approved = os.getenv("NEXE_APPROVED_MODULES", "").strip()
    if approved:
        return {m.strip() for m in approved.split(",") if m.strip()}
    elif is_prod:
        raise ValueError(
            "SECURITY ERROR: NEXE_APPROVED_MODULES is required in production. "
            "Set NEXE_APPROVED_MODULES or NEXE_ENV=development."
        )
    return None
