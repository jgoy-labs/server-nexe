"""
────────────────────────────────────
Server Nexe — Sidecar Config
Author: Jordi Goy
Location: core/sidecar_config.py
Description: Single source of truth for sidecar-mode runtime configuration.

Wraps the NEXE_* env vars (registered at core.config.NexeSettings) and exposes
**computed** fields needed when running as a Tauri sidecar:

- is_sidecar / is_production booleans (derived from env)
- cors_origins (includes tauri://localhost + http://localhost:1420 when is_sidecar)
- trusted_hosts (parsed from NEXE_TRUSTED_HOSTS)
- Fail-fast on missing required vars when is_sidecar=True

Goal: centralize what was scattered across middleware.py, lifespan_*.py,
paths/helpers.py, factory_security.py — the meta-bug "mode sidecar fictici"
documented at the project's meta-mode sidecar ADR.

═══════════════════════════════════════════════════════════════════════════
SidecarConfig vs NexeSettings — when to use which
═══════════════════════════════════════════════════════════════════════════

`core/sidecar_config.SidecarConfig` (this module):
  ▸ USE: runtime code that needs an immediate decision (CORS, paths, allowlist)
  ▸ FOCUS: subset of ~18 computed + derived fields for sidecar mode
  ▸ API: FROZEN dataclass (immutable, type-safe, no unparsed `Optional[str]`)
  ▸ FAIL-FAST: SidecarConfigError if a critical env var is missing
  ▸ CONSUMERS: middleware, factory_security, lifespan_*, paths/helpers
  ▸ Usage: `config = get_sidecar_config(); if config.is_sidecar: ...`

`core.config.NexeSettings` (Pydantic BaseSettings):
  ▸ USE: future admin panel — expose every NEXE_* to a dynamic UI
  ▸ FOCUS: registry of ~40+ fields with metadata (description, type, alias)
  ▸ API: mutable Pydantic class with introspectable `model_fields`
  ▸ NO FAIL-FAST: every field has a default (Optional or a value)
  ▸ CONSUMERS: admin panel (future), not runtime code
  ▸ Usage: `settings = NexeSettings(); admin_panel.render(settings.list_settings())`

Practical rule:
- You can derive a value safely at startup → SidecarConfig (fail-fast parsing).
- You want to show a value to the user with metadata → NexeSettings (.list_settings()).
- You want dynamic overrides after startup → neither (SidecarConfig is FROZEN; NexeSettings still has no setter).

Fields that exist in both (manually synced up to Session 2):
- host (NEXE_SERVER_HOST) / port (NEXE_SERVER_PORT) / lang / default_model
- model_engine / prompt_tier / logs_dir / approved_modules
Fields only on SidecarConfig (derived parse): is_sidecar, is_production,
cors_origins, trusted_hosts, vectors_dir, cache_dir, parent_pid.
Fields only on NexeSettings (raw env exposure): ollama_*, qdrant_url,
csrf_secret, encryption_enabled, bootstrap_*, autostart_ollama, vpn_*.

═══════════════════════════════════════════════════════════════════════════

Usage runtime:
    from core.sidecar_config import get_sidecar_config
    config = get_sidecar_config()
    if config.is_sidecar:
        # tauri://localhost is in config.cors_origins, etc.
        ...

Status: Initial implementation (2026-05-16). Basic impl
direct os.environ — integration with NexeSettings deferred to Session 2.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from core.config_catalog import default_for
from core.env_utils import parse_truthy as _parse_truthy


# Required env vars when running as sidecar (NEXE_SIDECAR=1).
# Tauri's spawn_sidecar_process injects more (NEXE_HOME, NEXE_DATA_DIR, etc.)
# but ONLY in release (sidecar_data_dir != None). In dev (`pnpm tauri dev`)
# it injects only the critical subset below. So we fail-fast ONLY on these
# (no reasonable fallback); the others have defaults in _resolve_paths().
#
# Anomaly discovered empirically: requiring NEXE_HOME/DATA_DIR/etc.
# broke `pnpm tauri dev` because dev mode does not inject them — SidecarConfigError
# propagated into setup_cors's defensive try/except, which fell back to server.toml
# CORS without Tauri origins → webview rejected.
SIDECAR_REQUIRED_ENV_VARS: tuple[str, ...] = (
    "NEXE_PRIMARY_API_KEY",  # Auth: without this there is no security
    "NEXE_PORT",             # Ephemeral port from the Tauri spawn — without it, port 9119 collides
)

# Env vars the Tauri spawn injects in release (informational, NOT fail-fast).
# When they are missing (dev mode), _resolve_paths() uses reasonable fallbacks (~/.nexe/, cwd).
SIDECAR_RELEASE_ENV_VARS: tuple[str, ...] = (
    "NEXE_HOME",
    "NEXE_DATA_DIR",
    "NEXE_LOGS_DIR",
    "NEXE_CACHE_DIR",
    "NEXE_QDRANT_PATH",
    "NEXE_PARENT_PID",
)

# Tauri-specific origins appended to CORS allowlist when is_sidecar=True.
# - tauri://localhost: release webview (custom scheme)
# - http://localhost:1420: Vite dev server (pnpm tauri dev)
# - http://tauri.localhost: some Tauri 2.x setups (rare)
# Resolves a startup configuration anomaly.
SIDECAR_CORS_ORIGINS: tuple[str, ...] = (
    "tauri://localhost",
    "http://localhost:1420",
    "http://tauri.localhost",
)

# Default trusted hosts when NEXE_TRUSTED_HOSTS is unset.
DEFAULT_TRUSTED_HOSTS: tuple[str, ...] = ("127.0.0.1", "::1", "localhost")  # nosemgrep

# Default fallbacks for standalone mode (NO NEXE_SIDECAR). D-P catalog.
_DEFAULT_HOST = default_for("server_host")  # nosemgrep
_DEFAULT_PORT = default_for("server_port")  # nosemgrep — server-nexe canonical port

# Port validation range — matches NexeSettings ge/le constraints at core/config.py.
# Below the registered ports cutoff require root/elevated permissions; above the
# TCP max are not valid network ports.
_MIN_PORT = 1024   # nosemgrep — RFC IANA registered ports cutoff
_MAX_PORT = 65535  # nosemgrep — RFC TCP/IP max port number

class SidecarConfigError(RuntimeError):
    """Raised when SidecarConfig.from_env() detects an invalid environment.

    Common causes:
    - is_sidecar=True but a required NEXE_* var is missing
    - NEXE_PORT or NEXE_SERVER_PORT not parseable as int
    """


# ─────────────────────────────────────────────────────────────────────
# Internal helpers — split from from_env() to keep CCN ≤ 15
# ─────────────────────────────────────────────────────────────────────


def _check_sidecar_required(is_sidecar: bool) -> None:
    """Raise SidecarConfigError if is_sidecar=True and any required var missing."""
    if not is_sidecar:
        return
    missing = [v for v in SIDECAR_REQUIRED_ENV_VARS if not os.environ.get(v)]
    if missing:
        raise SidecarConfigError(
            f"SECURITY: missing required env vars for sidecar mode: "
            f"{missing}. Tauri spawn must inject all of "
            f"{list(SIDECAR_REQUIRED_ENV_VARS)}."
        )


def _resolve_paths(is_sidecar: bool) -> dict[str, Path]:
    """Resolve the 5 path env vars with standalone fallbacks to ~/.nexe/."""
    home_dir = Path(os.environ.get("NEXE_HOME", os.getcwd())).expanduser()
    logs_dir = Path(
        os.environ.get("NEXE_LOGS_DIR", str(Path.home() / ".nexe" / "logs"))
    ).expanduser()
    data_dir = Path(
        os.environ.get("NEXE_DATA_DIR", str(Path.home() / ".nexe" / "data"))
    ).expanduser()
    cache_dir = Path(
        os.environ.get("NEXE_CACHE_DIR", str(Path.home() / ".nexe" / "cache"))
    ).expanduser()
    vectors_fallback = (
        str(data_dir / "vectors") if is_sidecar else default_for("qdrant_path")
    )
    vectors_dir = Path(
        os.environ.get("NEXE_QDRANT_PATH", vectors_fallback)
    ).expanduser()
    return {
        "home_dir": home_dir,
        "logs_dir": logs_dir,
        "data_dir": data_dir,
        "cache_dir": cache_dir,
        "vectors_dir": vectors_dir,
    }


def _resolve_port() -> int:
    """Parse NEXE_PORT (priority) or NEXE_SERVER_PORT or _DEFAULT_PORT.

    Validates port in range [_MIN_PORT, _MAX_PORT] (matches NexeSettings).
    Uses explicit `is not None` checks (not `or`) so that NEXE_PORT="0" is
    detected as invalid range instead of silently falling through to fallback.

    Raises SidecarConfigError if value present but not int or out of range.
    """
    raw_port: Optional[str] = os.environ.get("NEXE_PORT")
    if raw_port is None or raw_port == "":
        raw_port = os.environ.get("NEXE_SERVER_PORT")
    if raw_port is None or raw_port == "":
        raw_port = str(_DEFAULT_PORT)
    try:
        port = int(raw_port)
    except ValueError as e:
        raise SidecarConfigError(
            f"NEXE_PORT/NEXE_SERVER_PORT not parseable as int: {raw_port!r}"
        ) from e
    if port < _MIN_PORT or port > _MAX_PORT:
        raise SidecarConfigError(
            f"NEXE_PORT/NEXE_SERVER_PORT out of range "
            f"[{_MIN_PORT}, {_MAX_PORT}]: {port}"
        )
    return port


def _resolve_cors_origins(is_sidecar: bool, port: int) -> tuple[str, ...]:
    """Compute CORS allowlist: dev origins + current port + Tauri if sidecar."""
    base_origins = (
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        f"http://localhost:{port}",
        f"http://127.0.0.1:{port}",
    )
    if is_sidecar:
        return base_origins + SIDECAR_CORS_ORIGINS
    return base_origins


def _resolve_trusted_hosts() -> tuple[str, ...]:
    """Return DEFAULT_TRUSTED_HOSTS plus any NEXE_TRUSTED_HOSTS CSV entries.

    Mirrors core.config.get_trusted_hosts(): the defaults are never dropped,
    so adding an alias cannot lock the local machine out of its own server.

    #864: was NEXE_LOCALHOST_ALIASES — renamed so an alias added for the
    bootstrap client-IP check (core.config.get_localhost_aliases()) cannot
    silently widen the sidecar's Host-header allow-list too.
    """
    hosts = list(DEFAULT_TRUSTED_HOSTS)
    raw = os.environ.get("NEXE_TRUSTED_HOSTS", "")
    for entry in raw.split(","):
        entry = entry.strip()
        if entry and entry not in hosts:
            hosts.append(entry)
    return tuple(hosts)


def _resolve_parent_pid() -> Optional[int]:
    """Parse NEXE_PARENT_PID as int; None if unset or invalid (watchdog skips)."""
    raw_pid = os.environ.get("NEXE_PARENT_PID")
    if not raw_pid:
        return None
    try:
        return int(raw_pid)
    except ValueError:
        return None


def _resolve_approved_modules() -> tuple[str, ...]:
    """Parse NEXE_APPROVED_MODULES CSV, empty tuple if unset."""
    raw = os.environ.get("NEXE_APPROVED_MODULES", "")
    return tuple(m.strip() for m in raw.split(",") if m.strip())


def _resolve_bootstrap_ttl() -> int:
    """Parse NEXE_BOOTSTRAP_TTL as int (minutes); default 30.

    Raises SidecarConfigError if value present but not parseable as int.
    """
    raw = os.environ.get("NEXE_BOOTSTRAP_TTL")
    if raw is None or raw.strip() == "":
        return int(default_for("bootstrap_ttl"))
    try:
        return int(raw.strip())
    except ValueError as e:
        raise SidecarConfigError(
            f"NEXE_BOOTSTRAP_TTL not parseable as int: {raw!r}"
        ) from e


def _resolve_auto_ingest(is_sidecar: bool) -> bool:
    """NEXE_AUTO_INGEST_KNOWLEDGE: catalog default per mode, env wins when set."""
    raw = os.environ.get("NEXE_AUTO_INGEST_KNOWLEDGE")
    if raw is None or raw.strip() == "":
        return bool(default_for("auto_ingest_knowledge", sidecar=is_sidecar))
    return _parse_truthy(raw)


def _resolve_encryption_enabled() -> str:
    """Parse NEXE_ENCRYPTION_ENABLED — kept as string literal ('auto'/'true'/'false').

    Default 'auto' matches NexeSettings. The consumer (lifespan_crypto.py) decides
    how to interpret 'auto' (typically: enable if libsodium available).
    Returns lowercase normalized value.
    """
    raw = os.environ.get(
        "NEXE_ENCRYPTION_ENABLED", default_for("encryption_enabled")
    )
    return raw.strip().lower() or default_for("encryption_enabled")


@dataclass(frozen=True)
class SidecarConfig:
    """Immutable snapshot of sidecar-mode configuration, built once at startup.

    Build via SidecarConfig.from_env() or get_sidecar_config() (global singleton).

    All Path fields are expanduser-ed but NOT mkdir-ed: callers must mkdir before
    use (typically at first access from core/paths/helpers.py).
    """

    # === Mode ===
    is_sidecar: bool          # NEXE_SIDECAR=="1"
    is_production: bool       # NEXE_ENV.lower()=="production"

    # === Paths (always writable; mkdir lazy) ===
    home_dir: Path            # NEXE_HOME — code root
    logs_dir: Path            # NEXE_LOGS_DIR — log files
    data_dir: Path            # NEXE_DATA_DIR — user data, segregated from updates
    cache_dir: Path           # NEXE_CACHE_DIR — disposable caches
    vectors_dir: Path         # NEXE_QDRANT_PATH — Qdrant embedded DB

    # === Network ===
    host: str                 # NEXE_HOST or NEXE_SERVER_HOST or _DEFAULT_HOST
    port: int                 # NEXE_PORT or NEXE_SERVER_PORT or _DEFAULT_PORT
    cors_origins: tuple[str, ...]   # Base + SIDECAR_CORS_ORIGINS when is_sidecar
    trusted_hosts: tuple[str, ...]  # Parsed from NEXE_TRUSTED_HOSTS

    # === Auth ===
    api_key: str              # NEXE_PRIMARY_API_KEY
    parent_pid: Optional[int] # NEXE_PARENT_PID (Tauri spawn PID, for watchdog)
    approved_modules: tuple[str, ...]  # NEXE_APPROVED_MODULES parsed as CSV

    # === Engine ===
    default_model: str        # NEXE_DEFAULT_MODEL
    model_engine: Optional[str]   # NEXE_MODEL_ENGINE (ollama/mlx/llama_cpp)
    prompt_tier: str          # NEXE_PROMPT_TIER (full/compact)
    lang: str                 # NEXE_LANG (ca/es/en)

    # === Services (expanded fields for sidecar consumers) ===
    ollama_host: str          # NEXE_OLLAMA_HOST — default "http://localhost:11434"
    qdrant_url: Optional[str] # NEXE_QDRANT_URL — optional external Qdrant; embedded if None
    csrf_secret: Optional[str]    # NEXE_CSRF_SECRET — None disables persistent CSRF
    encryption_enabled: str   # NEXE_ENCRYPTION_ENABLED — "auto"/"true"/"false"
    auto_ingest_knowledge: bool   # NEXE_AUTO_INGEST_KNOWLEDGE
    bootstrap_ttl: int        # NEXE_BOOTSTRAP_TTL — minutes, default 30

    @classmethod
    def from_env(cls) -> "SidecarConfig":
        """Build SidecarConfig by reading os.environ.

        Delegates parsing to private _resolve_* helpers to keep CCN low.

        Raises:
            SidecarConfigError: if is_sidecar=True and any required env var
                is missing, or if NEXE_PORT/NEXE_SERVER_PORT is non-integer.
        """
        is_sidecar = _parse_truthy(os.environ.get("NEXE_SIDECAR"))
        env_value = os.environ.get(
            "NEXE_ENV",
            str(default_for("env", sidecar=is_sidecar)),
        )
        is_production = env_value.strip().lower() == "production"

        _check_sidecar_required(is_sidecar)
        paths = _resolve_paths(is_sidecar)
        port = _resolve_port()
        host = (
            os.environ.get("NEXE_HOST")
            or os.environ.get("NEXE_SERVER_HOST")
            or _DEFAULT_HOST
        )

        return cls(
            is_sidecar=is_sidecar,
            is_production=is_production,
            host=host,
            port=port,
            cors_origins=_resolve_cors_origins(is_sidecar, port),
            trusted_hosts=_resolve_trusted_hosts(),
            api_key=os.environ.get("NEXE_PRIMARY_API_KEY", ""),
            parent_pid=_resolve_parent_pid(),
            approved_modules=_resolve_approved_modules(),
            default_model=os.environ.get("NEXE_DEFAULT_MODEL", default_for("default_model")),
            model_engine=os.environ.get("NEXE_MODEL_ENGINE"),
            prompt_tier=os.environ.get("NEXE_PROMPT_TIER", default_for("prompt_tier")),
            lang=os.environ.get("NEXE_LANG", default_for("lang")),
            ollama_host=os.environ.get("NEXE_OLLAMA_HOST", default_for("ollama_host")),  # nosemgrep
            qdrant_url=os.environ.get("NEXE_QDRANT_URL"),
            csrf_secret=os.environ.get("NEXE_CSRF_SECRET"),
            encryption_enabled=_resolve_encryption_enabled(),
            auto_ingest_knowledge=_resolve_auto_ingest(is_sidecar),
            bootstrap_ttl=_resolve_bootstrap_ttl(),
            **paths,
        )


# ─────────────────────────────────────────────────────────────────────
# Global singleton (lazy init)
# ─────────────────────────────────────────────────────────────────────
#
# Thread safety: from_env() is idempotent for a given os.environ snapshot;
# concurrent racing init produces equivalent frozen objects. For test
# isolation use reset_sidecar_config().

_config: Optional[SidecarConfig] = None


def get_sidecar_config() -> SidecarConfig:
    """Return the global SidecarConfig, building it on first access."""
    global _config
    if _config is None:
        _config = SidecarConfig.from_env()
    return _config


def reset_sidecar_config() -> None:
    """Reset the global singleton — for tests only."""
    global _config
    _config = None


# ─────────────────────────────────────────────────────────────────────
# Import-guard helpers
# ─────────────────────────────────────────────────────────────────────
#
# These helpers wrap the try/except pattern that was duplicated in
# bootstrap.py, system.py, factory_app.py and factory_security.py: import
# get_sidecar_config() defensively and degrade gracefully if the
# config is unavailable. They replicate the previous logic/logs EXACTLY.

def resolve_core_env(raw_default: str, context: str, logger: "logging.Logger") -> str:
    """
    Resolve the canonical environment string, deferring to SidecarConfig.

    SidecarConfig.is_production is the canonical source for production vs
    non-production. The raw NEXE_ENV is kept to tell "development" apart from
    other non-production values such as "staging"/"test".

    Args:
      raw_default: Default value for NEXE_ENV when the env var is unset
        (replicates the per-call-site os.getenv default).
      context: Function name used in the fallback debug log line.
      logger: Caller's logger, so the log record keeps the original name.

    Returns:
      "production" if SidecarConfig reports production, otherwise the
      lowercased raw NEXE_ENV value.
    """
    core_env = os.getenv("NEXE_ENV", raw_default).lower()
    try:
        if get_sidecar_config().is_production:
            core_env = "production"
    except Exception as exc:
        logger.debug(
            "SidecarConfig unavailable in %s, using raw NEXE_ENV: %s",
            context,
            exc,
        )
    return core_env


def is_sidecar_mode(context: str, logger: "logging.Logger") -> bool:
    """
    Return whether the process runs as a sidecar, degrading to False on error.

    Wraps the defensive guard: if get_sidecar_config() fails for any
    reason, we assume we are NOT a sidecar (system.py's previous behavior).

    Args:
      context: Caller label used in the fallback debug log line.
      logger: Caller's logger, so the log record keeps the original name.

    Returns:
      True if running as sidecar, False otherwise (including on error).
    """
    try:
        return get_sidecar_config().is_sidecar
    except Exception as exc:
        logger.debug("%s: get_sidecar_config() failed (%s); proceeding non-sidecar", context, exc)
        return False
