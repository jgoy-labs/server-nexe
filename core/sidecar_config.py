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
- trusted_hosts (parsed from NEXE_LOCALHOST_ALIASES)
- Fail-fast on missing required vars when is_sidecar=True

Goal: centralize what was scattered across middleware.py, lifespan_*.py,
paths/helpers.py, factory_security.py — the meta-bug "mode sidecar fictici"
documented at the project's meta-mode sidecar ADR.

═══════════════════════════════════════════════════════════════════════════
SidecarConfig vs NexeSettings — quan usar cadascú
═══════════════════════════════════════════════════════════════════════════

`core/sidecar_config.SidecarConfig` (aquest mòdul):
  ▸ ÚS: codi runtime que necessita decisions immediates (CORS, paths, allowlist)
  ▸ FOCUS: subset de ~18 camps computats + derivats per a mode sidecar
  ▸ API: dataclass FROZEN (immutable, type-safe, no `Optional[str]` sense parse)
  ▸ FAIL-FAST: SidecarConfigError si manca env crítica
  ▸ CONSUMERS: middleware, factory_security, lifespan_*, paths/helpers
  ▸ Usage: `config = get_sidecar_config(); if config.is_sidecar: ...`

`core.config.NexeSettings` (BaseSettings Pydantic):
  ▸ ÚS: future admin panel — exposar tots els NEXE_* a UI dinàmica
  ▸ FOCUS: registry de ~40+ camps amb metadata (description, type, alias)
  ▸ API: classe Pydantic mutable amb `model_fields` introspectable
  ▸ NO FAIL-FAST: tots els camps tenen default (Optional o valor)
  ▸ CONSUMERS: panel admin (futur), no codi runtime
  ▸ Usage: `settings = NexeSettings(); admin_panel.render(settings.list_settings())`

Regla pràctica:
- Pots derivar un valor amb seguretat al startup → SidecarConfig (parsing fail-fast).
- Vols mostrar un valor a l'usuari amb metadata → NexeSettings (.list_settings()).
- Vols overrides dinàmics post-startup → cap dels dos (SidecarConfig és FROZEN; NexeSettings encara no té setter).

Fields that exist in both (manually synced up to Session 2):
- host (NEXE_SERVER_HOST) / port (NEXE_SERVER_PORT) / lang / default_model
- model_engine / prompt_tier / logs_dir / approved_modules
Camps només a SidecarConfig (parse derivat): is_sidecar, is_production,
cors_origins, trusted_hosts, vectors_dir, cache_dir, parent_pid.
Camps només a NexeSettings (raw env exposure): ollama_*, qdrant_url,
csrf_secret, encryption_enabled, bootstrap_*, autostart_ollama, vpn_*.

═══════════════════════════════════════════════════════════════════════════

Usage runtime:
    from core.sidecar_config import get_sidecar_config
    config = get_sidecar_config()
    if config.is_sidecar:
        # tauri://localhost is in config.cors_origins, etc.
        ...

Status: Initial implementation (2026-05-16). Impl bàsica
direct os.environ — integration with NexeSettings deferred to Session 2.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from core.env_utils import parse_truthy as _parse_truthy


# Required env vars when running as sidecar (NEXE_SIDECAR=1).
# Tauri's spawn_sidecar_process injecta més (NEXE_HOME, NEXE_DATA_DIR, etc.)
# però NOMÉS en release (sidecar_data_dir != None). En dev (`pnpm tauri dev`)
# només injecta el subset crític sotabaix. Per tant fem fail-fast SOLS d'aquestes
# (sense fallback raonable); les altres tenen defaults a _resolve_paths().
#
# Anomaly discovered empirically: requiring NEXE_HOME/DATA_DIR/etc.
# trencava `pnpm tauri dev` perquè dev mode no les injecta — SidecarConfigError
# es propagava al try/except defensiu de setup_cors, que feia fallback a server.toml
# CORS sense Tauri origins → webview rebutjat.
SIDECAR_REQUIRED_ENV_VARS: tuple[str, ...] = (
    "NEXE_PRIMARY_API_KEY",  # Auth: sense això no hi ha seguretat
    "NEXE_PORT",             # Port efímer del Tauri spawn — sense això collisió port 9119
)

# Env vars que Tauri spawn injecta en release (informatius, NO fail-fast).
# Quan falten (dev mode), _resolve_paths() usa fallbacks raonables (~/.nexe/, cwd).
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

# Default trusted hosts when NEXE_LOCALHOST_ALIASES is unset.
DEFAULT_TRUSTED_HOSTS: tuple[str, ...] = ("127.0.0.1", "::1", "localhost")  # nosemgrep

# Default fallbacks for standalone mode (NO NEXE_SIDECAR).
_DEFAULT_HOST = "127.0.0.1"  # nosemgrep
_DEFAULT_PORT = 9119  # nosemgrep — server-nexe canonical port

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
    vectors_fallback = str(data_dir / "vectors") if is_sidecar else "storage/vectors"
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
    """Parse NEXE_LOCALHOST_ALIASES CSV, fallback to DEFAULT_TRUSTED_HOSTS."""
    raw = os.environ.get("NEXE_LOCALHOST_ALIASES", "")
    if not raw.strip():
        return DEFAULT_TRUSTED_HOSTS
    return tuple(h.strip() for h in raw.split(",") if h.strip())


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
        return 30
    try:
        return int(raw.strip())
    except ValueError as e:
        raise SidecarConfigError(
            f"NEXE_BOOTSTRAP_TTL not parseable as int: {raw!r}"
        ) from e


def _resolve_encryption_enabled() -> str:
    """Parse NEXE_ENCRYPTION_ENABLED — kept as string literal ('auto'/'true'/'false').

    Default 'auto' matches NexeSettings. The consumer (lifespan_crypto.py) decides
    how to interpret 'auto' (typically: enable if libsodium available).
    Returns lowercase normalized value.
    """
    raw = os.environ.get("NEXE_ENCRYPTION_ENABLED", "auto")
    return raw.strip().lower() or "auto"


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
    trusted_hosts: tuple[str, ...]  # Parsed from NEXE_LOCALHOST_ALIASES

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
    qdrant_url: Optional[str] # NEXE_QDRANT_URL — Optional Qdrant extern; embedded if None
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
            "production" if is_sidecar else "development",
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
            default_model=os.environ.get("NEXE_DEFAULT_MODEL", ""),
            model_engine=os.environ.get("NEXE_MODEL_ENGINE"),
            prompt_tier=os.environ.get("NEXE_PROMPT_TIER", "full"),
            lang=os.environ.get("NEXE_LANG", "en"),
            # Services (prepared for future iterations)
            ollama_host=os.environ.get("NEXE_OLLAMA_HOST", "http://localhost:11434"),  # nosemgrep
            qdrant_url=os.environ.get("NEXE_QDRANT_URL"),
            csrf_secret=os.environ.get("NEXE_CSRF_SECRET"),
            encryption_enabled=_resolve_encryption_enabled(),
            auto_ingest_knowledge=_parse_truthy(os.environ.get("NEXE_AUTO_INGEST_KNOWLEDGE")),
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
# Aquests helpers encapsulen el patró try/except que estava duplicat a
# bootstrap.py, system.py, factory_app.py i factory_security.py: importar
# get_sidecar_config() de forma defensiva i degradar amb gràcia si la
# config no està disponible. Repliquen EXACTAMENT la lògica/logs previs.

def resolve_core_env(raw_default: str, context: str, logger: "logging.Logger") -> str:
    """
    Resolve the canonical environment string, deferring to SidecarConfig.

    SidecarConfig.is_production is the canonical source for produccio vs
    no-produccio. Es manté el raw NEXE_ENV per distingir "development" de
    valors no-produccio com "staging"/"test".

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

    Encapsula el guard defensiu: si get_sidecar_config() falla per qualsevol
    motiu, assumim que NO som sidecar (comportament previ de system.py).

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
