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
import logging
import os
import shutil
import stat
import tempfile
from pathlib import Path
from typing import Dict, Any, Optional

from core.env_utils import parse_port
from core.paths.constants import BASE_CONFIG_RELATIVE

import tomllib
import tomli_w  # write path (tomllib stdlib is read-only); uiri `toml` is banned — it silently truncates multiline strings containing \[ (#834)

try:
    from pydantic_settings import BaseSettings, SettingsConfigDict
    from pydantic import Field
    _PYDANTIC_SETTINGS_AVAILABLE = True
except ImportError:  # pragma: no cover
    # Fallback stubs so the names exist for static analyzers (pyright);
    # NexeSettings class is only defined when _PYDANTIC_SETTINGS_AVAILABLE is True.
    BaseSettings = object  # type: ignore[misc,assignment]
    SettingsConfigDict = dict  # type: ignore[misc,assignment]

    def Field(*args: Any, **kwargs: Any) -> Any:  # type: ignore[no-redef,misc,assignment]
        return args[0] if args else None

    _PYDANTIC_SETTINGS_AVAILABLE = False

logger = logging.getLogger(__name__)


def _apply_env_overrides(merged: Dict[str, Any]) -> Dict[str, Any]:
    """Apply environment variable overrides to a loaded config dict.

    Priority: env var > server.toml > built-in default.
    Currently handles: NEXE_SERVER_PORT.
    """
    # MC-093: validate + range-check via the shared parser (fail-fast with a
    # clear message instead of a raw int() that crashes later in uvicorn).
    port = parse_port(os.environ.get("NEXE_SERVER_PORT"), var_name="NEXE_SERVER_PORT")
    if port is not None:
        merged['core']['server']['port'] = port
        logger.debug("NEXE_SERVER_PORT override: port=%s", port)
    return merged


def _resolve_encryption_enabled(env_value: str, *, sqlcipher_available: bool) -> bool:
    """P1-D: Determine whether encryption should be enabled given the env config and availability.

    - 'auto' or '' (empty/legacy): enable if sqlcipher3 is available, otherwise OFF
    - 'true': always ON (caller checks SQLCIPHER_AVAILABLE and raises RuntimeError if needed)
    - 'false': always OFF
    - any other value: OFF (safe default behaviour)

    Pure function (no side effects) so it can be tested directly.
    Logging is done by the caller (lifespan startup). Lives here (a leaf config
    module without internal imports) so both core.lifespan and core.lifespan_crypto
    can import it without a circular dependency.
    """
    normalized = env_value.strip().lower()
    if normalized in ('', 'auto'):
        return sqlcipher_available
    if normalized == 'true':
        return True
    if normalized == 'false':
        return False
    return False  # unknown value → OFF


def encryption_is_mandatory(env_value: str) -> bool:
    """WS3-03: True only when the user EXPLICITLY demanded encryption.

    'auto' tolerates a plaintext fallback (with a loud error log); 'true'
    must fail closed — a failed SQLCipher migration may never silently
    open PII in plaintext. Pure function, same normalization as
    _resolve_encryption_enabled.
    """
    return env_value.strip().lower() == 'true'


# Default configuration
DEFAULT_CONFIG = {
    'core': {
        'server': {
            'host': '127.0.0.1',  # nosemgrep
            'port': 9119,
            'cors_origins': ['http://localhost:3000']
        },
        'environment': {
            'mode': 'production'  # 'production' or 'development'
        }
    },
    'security': {
        'encryption': {
            # MC-092: crypto is toggled ONLY by NEXE_ENCRYPTION_ENABLED — a config
            # key here would be dead (nothing reads it) and would mislead users
            # into thinking the TOML turns encryption on/off. Only warn_unencrypted
            # is read (lifespan_crypto).
            'warn_unencrypted': True
        }
    }
}

# Standard search paths for config — kept for find_config_path() backward compat
CONFIG_SEARCH_PATHS = [
    "server.toml",
    BASE_CONFIG_RELATIVE,
    "config/server.toml"
]

# Priority order: DEFAULT < personality/server.toml (BASE) < root/config server.toml (OVERRIDE) < ENV vars
_BASE_CONFIG_FILES = [BASE_CONFIG_RELATIVE]
_OVERRIDE_CONFIG_FILES = ["server.toml", "config/server.toml"]


def _safe_repo_root() -> Path:
    """Best-effort repo-root resolution for config search fallback.

    Replaces the previous ``Path.cwd()`` fallback, which depended on the
    arbitrary directory the process was launched from and silently picked
    up the wrong tree when launched as a Tauri sidecar (the executable
    runs from the user's home or `/`). ``get_repo_root()`` honours
    ``NEXE_HOME`` and the marker-file heuristics; if it can't resolve the
    root we still surface ``Path.cwd()`` rather than blowing up here.
    """
    try:
        from core.paths.detection import get_repo_root
        return get_repo_root()
    except Exception as exc:
        logger = logging.getLogger(__name__)
        logger.debug(
            "get_repo_root() unavailable in find_config_path/load_config, "
            "falling back to Path.cwd(): %s",
            exc,
        )
        return Path.cwd()


def find_config_path(project_root: Optional[Path] = None) -> Optional[Path]:
    """
    Find the primary configuration file path (first-wins, for logging).

    Returns the first file found in CONFIG_SEARCH_PATHS.
    Note: load_config() uses multi-file merge logic; this helper is for logging/compat.

    Args:
        project_root: Optional project root directory

    Returns:
        Path to config file or None if not found
    """
    base = Path(project_root) if project_root else _safe_repo_root()

    for config_rel in CONFIG_SEARCH_PATHS:
        config_path = base / config_rel
        if config_path.exists():
            return config_path.resolve()

    return None


def _load_single_config_file(found_path: Path, i18n) -> Dict[str, Any]:
    """Load and merge a single TOML config file into DEFAULT_CONFIG. Returns merged dict."""
    try:
        if i18n:
            logger.info(i18n.t("server_core.startup.loading_config", path=str(found_path)))
        else:
            logger.info("Loading config from: %s", found_path)
        with open(found_path, 'rb') as f:
            raw = tomllib.load(f)
        merged = _deep_merge(copy.deepcopy(DEFAULT_CONFIG), raw)
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


def _load_multi_file_config(base: Path, i18n) -> Dict[str, Any]:
    """Merge base + override TOML files into DEFAULT_CONFIG. Returns merged dict."""
    merged = copy.deepcopy(DEFAULT_CONFIG)
    loaded_any = False

    for rel in _BASE_CONFIG_FILES:
        path = base / rel
        if path.exists():
            try:
                with open(path, 'rb') as f:
                    merged = _deep_merge(merged, tomllib.load(f))
                loaded_any = True
                logger.info("Config base loaded from: %s", path)
            except Exception as e:
                logger.error("Error loading base config %s: %s", path, e)

    for rel in _OVERRIDE_CONFIG_FILES:
        path = base / rel
        if path.exists():
            try:
                with open(path, 'rb') as f:
                    merged = _deep_merge(merged, tomllib.load(f))
                loaded_any = True
                logger.info("Config override loaded from: %s", path)
            except Exception as e:
                logger.error("Error loading override config %s: %s", path, e)
            break  # Only first override wins

    if not loaded_any:
        if i18n:
            logger.warning(i18n.t("server_core.startup.config_not_found"))
        else:
            logger.warning("No config file found, using defaults")

    return _apply_env_overrides(merged)


def load_config(
    project_root: Optional[Path] = None,
    i18n=None,
    config_path: Optional[Path] = None
) -> Dict[str, Any]:
    """
    Load configuration with multi-file deep-merge.

    Priority (low → high): DEFAULT < personality/server.toml < root server.toml < ENV vars

    When config_path is given, uses that single file (backward compat for direct overrides).
    When searching by project_root, applies the full BASE + OVERRIDE merge pattern.

    Args:
        project_root: Path to project root directory
        i18n: I18n manager for translated messages (optional)
        config_path: Direct path to config file (skips multi-file search)

    Returns:
        Dict with configuration data
    """
    # Direct path: single file, no multi-file logic (backward compat)
    if config_path and Path(config_path).exists():
        return _load_single_config_file(Path(config_path), i18n)

    # Multi-file merge: DEFAULT < personality/server.toml < root server.toml < ENV vars
    base = Path(project_root) if project_root else _safe_repo_root()
    return _load_multi_file_config(base, i18n)


def atomic_toml_write(path: Path, data: Dict[str, Any], *, backup: bool = True) -> None:
    """
    Write a TOML file without ever leaving it truncated (#834).

    Order matters: (1) serialise BEFORE touching disk, so a serialisation
    error can never destroy the existing file; (2) keep a rolling `.bak` of
    the previous content (per-SAVE semantics — multi-write flows pass
    backup=False on later writes so the .bak keeps the pre-command state);
    (3) write to a per-writer temp file in the SAME directory (mkstemp:
    concurrent writers never promote each other's partial file), fsync it,
    and (4) swap it in with os.replace (atomic on the same filesystem),
    preserving the target's permission bits and writing THROUGH symlinks.
    `.bak`/`.tmp` suffixes deliberately do not end in `.toml` so manifest
    globs never pick them up.
    """
    path = Path(path)
    if path.exists():
        path = path.resolve()  # write through symlinks, never replace the link itself
    payload = tomli_w.dumps(data)
    if backup and path.exists():
        shutil.copy2(path, path.with_name(path.name + ".bak"))
    fd, tmp_name = tempfile.mkstemp(
        dir=path.parent, prefix=path.name + ".", suffix=".tmp"
    )
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(payload.encode("utf-8"))
            f.flush()
            os.fsync(f.fileno())  # survive power loss right after the replace
        if path.exists():
            os.chmod(tmp, stat.S_IMODE(os.stat(path).st_mode))  # keep 0600 et al.
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def save_config(config: Dict[str, Any], config_path: Path) -> bool:
    """
    Save configuration to a TOML file (atomic, with .bak backup).

    Args:
        config: Configuration dictionary to save
        config_path: Path to save config file

    Returns:
        True if saved successfully
    """
    try:
        atomic_toml_write(Path(config_path), config)
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

    Uses multi-file merge (DEFAULT < personality/server.toml < root server.toml < ENV vars).

    Args:
        reload: Force reload from file

    Returns:
        Configuration dictionary
    """
    global _config, _config_path

    if _config is None or reload:
        _config_path = find_config_path()  # For get_config_path() / logging only
        _config = load_config()  # Multi-file merge from cwd

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


def get_module_allowlist(config: Optional[Dict[str, Any]] = None) -> Optional[set]:
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
    # prefer SidecarConfig.is_production over reading NEXE_ENV directly,
    # fallback to os.getenv per backward-compat (tests/scripts sense singleton i
    # tests que muten NEXE_ENV runtime sense rebuild del singleton).
    raw_env_is_prod = os.getenv("NEXE_ENV", "production").lower() == "production"
    sidecar_is_prod = False
    try:
        from core.sidecar_config import get_sidecar_config
        sidecar_is_prod = get_sidecar_config().is_production
    except Exception as exc:
        logger.debug(
            "SidecarConfig unavailable in get_module_allowlist, "
            "using NEXE_ENV fallback: %s",
            exc,
        )
    is_prod_env = sidecar_is_prod or raw_env_is_prod
    config_mode = ""
    if config:
        config_mode = config.get("core", {}).get("environment", {}).get("mode", "")
    is_prod = is_prod_env or config_mode == "production"

    approved = os.getenv("NEXE_APPROVED_MODULES", "").strip()
    if approved:
        return {m.strip() for m in approved.split(",") if m.strip()}
    elif is_prod:
        raise ValueError(
            "SECURITY ERROR: NEXE_APPROVED_MODULES is required in production. "
            "Set NEXE_APPROVED_MODULES or NEXE_ENV=development."
        )
    return None


# Localhost aliases — single source of truth (AI audit hardcode fix)
# Always includes 127.0.0.1, ::1, localhost. NEXE_LOCALHOST_ALIASES adds extra
# entries (comma-separated). Used by bootstrap IP allowlist + middleware host checks.
#
# ::1 is here for the CLIENT IP comparison in core/endpoints/bootstrap.py, where
# request.client.host is the bare "::1". It can never match a Host header:
# TrustedHostMiddleware splits on ":" so any IPv6 Host is rejected — which is why
# core/server/runner.py refuses to bind to an IPv6 host in the first place.
DEFAULT_LOCALHOST_ALIASES = ["127.0.0.1", "::1", "localhost"]  # nosemgrep


def get_localhost_aliases() -> list:
    """Return list of IPs/hostnames considered localhost.

    The defaults are ALWAYS included; NEXE_LOCALHOST_ALIASES (comma-separated)
    only ADDS to them. It used to replace them, which meant that setting a
    single alias evicted 127.0.0.1/::1/localhost from both the TrustedHost
    allow-list and the bootstrap IP allow-list — locking the machine running
    the server out of its own service, with no hint as to why.

    Duplicates are dropped and the order is deterministic (defaults first).
    """
    aliases = list(DEFAULT_LOCALHOST_ALIASES)
    custom = os.getenv("NEXE_LOCALHOST_ALIASES", "")
    for entry in custom.split(","):
        entry = entry.strip()
        if entry and entry not in aliases:
            aliases.append(entry)
    return aliases


# Network defaults — single source of truth (AI audit hardcode fix Q4)
# Used to centralize the previously-hardcoded "9119" / "127.0.0.1" lists  # nosemgrep
# spread across runner.py, lifespan.py, middleware.py, cli/*, installer/tray.py
# and plugins/web_ui_module/module.py.
DEFAULT_HOST = "127.0.0.1"  # nosemgrep
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
# NexeSettings — Registry of env vars for the future admin panel
#
# Single source of truth for all NEXE_* env vars.
# Does not replace existing consumers (direct os.getenv);
# acts as a registry for dynamic discovery.
# Every new env var is added here and becomes available in the panel.
# ─────────────────────────────────────────────────────────────

if _PYDANTIC_SETTINGS_AVAILABLE:
    class NexeSettings(BaseSettings):  # pyright: ignore[reportGeneralTypeIssues]  # BaseSettings is bound to real class when flag True; pyright sees union with object fallback
        """Pydantic settings model that maps every ``NEXE_*`` env var to a typed field.

        Acts as the single source of truth for server configuration.
        New env vars are added here and become discoverable in the admin panel.
        """

        model_config = SettingsConfigDict(
            env_file=".env",
            extra="ignore",
            populate_by_name=True,
        )

        # --- Server ---
        server_host: str = Field("127.0.0.1", description="Bind host del server", alias="NEXE_SERVER_HOST")  # nosemgrep
        server_port: int = Field(9119, description="Port del server (1024-65535)", alias="NEXE_SERVER_PORT", ge=1024, le=65535)  # nosemgrep: hardcode.port_number — configurable via env NEXE_SERVER_PORT
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
        lang: str = Field("en", description="Idioma del servidor (ca|es|en)", alias="NEXE_LANG")
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
            """For the future admin panel: list all settings with metadata.

            Returns:
                List of dicts with: name (env var), field, default, description, type.
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
