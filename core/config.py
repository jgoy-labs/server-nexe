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

try:
    from pydantic_settings import BaseSettings, SettingsConfigDict
    from pydantic import Field
    _PYDANTIC_SETTINGS_AVAILABLE = True
except ImportError:  # pragma: no cover
    _PYDANTIC_SETTINGS_AVAILABLE = False

logger = logging.getLogger(__name__)


def _apply_env_overrides(merged: Dict[str, Any]) -> Dict[str, Any]:
    """Apply environment variable overrides to a loaded config dict.

    Priority: env var > server.toml > built-in default.
    Currently handles: NEXE_SERVER_PORT.
    """
    raw_port = os.environ.get("NEXE_SERVER_PORT")
    if raw_port:
        merged['core']['server']['port'] = int(raw_port)  # ValueError if not int (fail-fast)
        logger.debug("NEXE_SERVER_PORT override: port=%s", raw_port)
    return merged


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
        return _apply_env_overrides(copy.deepcopy(DEFAULT_CONFIG))

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

        return _apply_env_overrides(merged)

    except Exception as e:
        if i18n:
            logger.error(i18n.t("server_core.startup.config_error",
                                path=str(found_path), error=str(e)))
        else:
            logger.error("Error loading config from %s: %s", found_path, e)
        return _apply_env_overrides(copy.deepcopy(DEFAULT_CONFIG))


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


# Localhost aliases — single source of truth (Gemini hardcode fix)
# Default: 127.0.0.1, ::1, localhost. Override via NEXE_LOCALHOST_ALIASES env
# (comma-separated). Used by bootstrap IP allowlist + middleware host checks.
DEFAULT_LOCALHOST_ALIASES = ["127.0.0.1", "::1", "localhost"]


def get_localhost_aliases() -> list:
    """Return list of IPs/hostnames considered localhost.

    Reads NEXE_LOCALHOST_ALIASES env var (comma-separated) if set,
    otherwise returns DEFAULT_LOCALHOST_ALIASES. Used to centralize
    the previously-hardcoded ['127.0.0.1', '::1', 'localhost'] lists
    spread across bootstrap.py and middleware.py (Gemini finding).
    """
    custom = os.getenv("NEXE_LOCALHOST_ALIASES", "").strip()
    if custom:
        return [s.strip() for s in custom.split(",") if s.strip()]
    return list(DEFAULT_LOCALHOST_ALIASES)


# Network defaults — single source of truth (Gemini hardcode fix Q4)
# Used to centralize the previously-hardcoded "9119" / "127.0.0.1" lists
# spread across runner.py, lifespan.py, middleware.py, cli/*, installer/tray.py
# and plugins/web_ui_module/module.py.
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9119


def get_default_host() -> str:
    """Return the default server host.

    Reads NEXE_SERVER_HOST env var if set, otherwise returns DEFAULT_HOST.
    Used as fallback for `config.get('host', ...)` patterns across the
    codebase to remove hardcoded literals.
    """
    return os.environ.get("NEXE_SERVER_HOST", DEFAULT_HOST)


def get_default_port() -> int:
    """Return the default server port.

    Reads NEXE_SERVER_PORT env var if set, otherwise returns DEFAULT_PORT.
    Raises ValueError if NEXE_SERVER_PORT is set but not a valid integer
    (fail-fast: invalid config should not silently fall back).
    """
    raw = os.environ.get("NEXE_SERVER_PORT")
    if raw is None or raw == "":
        return DEFAULT_PORT
    return int(raw)


def get_server_url(scheme: str = "http") -> str:
    """Return canonical server URL based on env / defaults.

    Args:
        scheme: URL scheme (http or https). Default: http.

    Returns:
        f"{scheme}://{host}:{port}" using NEXE_SERVER_HOST/NEXE_SERVER_PORT
        env vars or DEFAULT_HOST/DEFAULT_PORT.

    Used by core/cli/config.py and installer/tray.py to remove hardcoded
    "http://localhost:9119" / "http://127.0.0.1:9119" literals (Q4.2).
    """
    return f"{scheme}://{get_default_host()}:{get_default_port()}"


# ─────────────────────────────────────────────────────────────
# NexeSettings — Registry d'env vars per al futur panell admin
#
# Font única de veritat de totes les NEXE_* env vars.
# No substitueix els consumidors existents (os.getenv directe);
# actua com a registry per descobriment dinàmic.
# Tota nova env var s'afegeix aquí i queda disponible al panell.
# ─────────────────────────────────────────────────────────────

if _PYDANTIC_SETTINGS_AVAILABLE:
    class NexeSettings(BaseSettings):
        model_config = SettingsConfigDict(
            env_file=".env",
            extra="ignore",
            populate_by_name=True,
        )

        # --- Server ---
        server_host: str = Field("127.0.0.1", description="Bind host del server", alias="NEXE_SERVER_HOST")
        server_port: int = Field(9119, description="Port del server (1024-65535)", alias="NEXE_SERVER_PORT", ge=1024, le=65535)
        env: str = Field("production", description="Entorn d'execució (production|development)", alias="NEXE_ENV")
        home: Optional[str] = Field(None, description="Directori arrel del servidor", alias="NEXE_HOME")
        logs_dir: Optional[str] = Field(None, description="Directori de logs", alias="NEXE_LOGS_DIR")

        # --- Auth / Security ---
        primary_api_key: str = Field("", description="API key principal (requerida en producció)", alias="NEXE_PRIMARY_API_KEY")
        admin_api_key: Optional[str] = Field(None, description="API key d'administrador", alias="NEXE_ADMIN_API_KEY")
        csrf_secret: Optional[str] = Field(None, description="Secret per a tokens CSRF", alias="NEXE_CSRF_SECRET")
        approved_modules: Optional[str] = Field(None, description="Mòduls aprovats (comma-separated, requerit en prod)", alias="NEXE_APPROVED_MODULES")
        localhost_aliases: str = Field("127.0.0.1,::1,localhost", description="Adreces considerades localhost (comma-separated)", alias="NEXE_LOCALHOST_ALIASES")
        encryption_enabled: str = Field("auto", description="Activar SQLCIPHER (true|false|auto)", alias="NEXE_ENCRYPTION_ENABLED")
        vpn_allowed_ips: str = Field("", description="IPs VPN permeses per bootstrap (comma-separated)", alias="NEXE_VPN_ALLOWED_IPS")
        master_key: Optional[str] = Field(None, description="Clau mestra per a derivació de claus HKDF", alias="NEXE_MASTER_KEY")

        # --- CLI / Client ---
        api_base_url: Optional[str] = Field(None, description="URL base de l'API per al CLI", alias="NEXE_API_BASE_URL")
        server_url: Optional[str] = Field(None, description="URL del server (override)", alias="NEXE_SERVER_URL")
        timeout: Optional[float] = Field(None, description="Timeout requests CLI (segons)", alias="NEXE_TIMEOUT")
        verify_ssl: Optional[str] = Field(None, description="Verificar SSL (true|false)", alias="NEXE_VERIFY_SSL")
        color: Optional[str] = Field(None, description="Mode color CLI (true|false|auto)", alias="NEXE_COLOR")
        cli_health_timeout: float = Field(5.0, description="Timeout health check CLI (segons)", alias="NEXE_CLI_HEALTH_TIMEOUT")

        # --- Model engine ---
        model_engine: Optional[str] = Field(None, description="Backend LLM actiu (ollama|mlx|llama_cpp)", alias="NEXE_MODEL_ENGINE")
        default_model: str = Field("", description="Model per defecte", alias="NEXE_DEFAULT_MODEL")
        mlx_model: Optional[str] = Field(None, description="Model MLX", alias="NEXE_MLX_MODEL")
        llama_cpp_model: Optional[str] = Field(None, description="Path model llama.cpp", alias="NEXE_LLAMA_CPP_MODEL")
        default_max_tokens: Optional[int] = Field(None, description="Màxim tokens per resposta", alias="NEXE_DEFAULT_MAX_TOKENS")
        prompt_tier: Optional[str] = Field(None, description="Nivell de prompt del sistema (full|compact)", alias="NEXE_PROMPT_TIER")

        # --- Ollama ---
        ollama_host: str = Field("http://localhost:11434", description="URL del servidor Ollama", alias="NEXE_OLLAMA_HOST")
        ollama_model: Optional[str] = Field(None, description="Model Ollama per defecte", alias="NEXE_OLLAMA_MODEL")
        ollama_num_ctx: Optional[int] = Field(None, description="Context window Ollama (tokens)", alias="NEXE_OLLAMA_NUM_CTX")
        ollama_stream_timeout: float = Field(300.0, description="Timeout streaming Ollama (segons)", alias="NEXE_OLLAMA_STREAM_TIMEOUT")
        ollama_think: Optional[str] = Field(None, description="Activar mode think Ollama (true|false)", alias="NEXE_OLLAMA_THINK")
        ollama_health_timeout: float = Field(5.0, description="Timeout health Ollama (segons)", alias="NEXE_OLLAMA_HEALTH_TIMEOUT")
        ollama_unload_timeout: float = Field(10.0, description="Timeout unload model Ollama (segons)", alias="NEXE_OLLAMA_UNLOAD_TIMEOUT")
        autostart_ollama: Optional[str] = Field(None, description="Iniciar Ollama automàticament (true|false)", alias="NEXE_AUTOSTART_OLLAMA")

        # --- Qdrant ---
        qdrant_path: str = Field("storage/vectors", description="Path base de dades Qdrant embedded", alias="NEXE_QDRANT_PATH")
        qdrant_url: Optional[str] = Field(None, description="URL Qdrant extern (si no embedded)", alias="NEXE_QDRANT_URL")

        # --- RAG / Language ---
        lang: str = Field("ca", description="Idioma del servidor (ca|es|en)", alias="NEXE_LANG")
        rag_docs_threshold: float = Field(0.4, description="Llindar similaritat RAG docs", alias="NEXE_RAG_DOCS_THRESHOLD")
        rag_knowledge_threshold: float = Field(0.35, description="Llindar similaritat RAG knowledge", alias="NEXE_RAG_KNOWLEDGE_THRESHOLD")
        rag_memory_threshold: float = Field(0.3, description="Llindar similaritat RAG memory", alias="NEXE_RAG_MEMORY_THRESHOLD")
        auto_ingest_knowledge: Optional[str] = Field(None, description="Ingerir knowledge automàticament en iniciar (true|false)", alias="NEXE_AUTO_INGEST_KNOWLEDGE")
        max_context_ratio: float = Field(0.3, description="Proporció màxima del context window per a l'historial", alias="NEXE_MAX_CONTEXT_RATIO")
        default_context_window: int = Field(8192, description="Mida context window per defecte (tokens)", alias="NEXE_DEFAULT_CONTEXT_WINDOW")

        # --- Runtime / Dev ---
        dev_mode: Optional[str] = Field(None, description="Mode desenvolupament (true|false)", alias="NEXE_DEV_MODE")
        docker: Optional[str] = Field(None, description="Execució en contenidor Docker (true|false)", alias="NEXE_DOCKER")
        no_tray: Optional[str] = Field(None, description="Desactivar icona tray macOS (true|false)", alias="NEXE_NO_TRAY")
        tray_pid: Optional[str] = Field(None, description="PID del procés tray (injectat per tray.py)", alias="NEXE_TRAY_PID")
        force_reload: str = Field("false", description="Forçar recàrrega de l'app en canvis (true|false)", alias="NEXE_FORCE_RELOAD")

        # --- Bootstrap ---
        bootstrap_ttl: int = Field(30, description="TTL del token bootstrap (segons)", alias="NEXE_BOOTSTRAP_TTL")
        bootstrap_display: bool = Field(True, description="Mostrar token bootstrap a la consola", alias="NEXE_BOOTSTRAP_DISPLAY")
        bootstrap_auto_renew: bool = Field(True, description="Renovar token bootstrap automàticament", alias="NEXE_BOOTSTRAP_AUTO_RENEW")
        auto_clean_enabled: bool = Field(False, description="Activar neteja automàtica de dades antigues", alias="NEXE_AUTO_CLEAN_ENABLED")
        auto_clean_dry_run: bool = Field(True, description="Executar neteja automàtica en mode simulació", alias="NEXE_AUTO_CLEAN_DRY_RUN")

        @classmethod
        def list_settings(cls) -> list[dict]:
            """Per al futur panell admin: llista totes les settings amb metadata.

            Returns:
                Llista de dicts amb: name (env var), field, default, description, type.
            """
            return [
                {
                    "name": (field_info.alias or name).upper(),
                    "field": name,
                    "default": field_info.default,
                    "description": field_info.description,
                    "type": str(field_info.annotation),
                }
                for name, field_info in cls.model_fields.items()
            ]
