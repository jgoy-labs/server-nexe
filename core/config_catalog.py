"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/config_catalog.py
Description: D-P — declaration-only catalogue of config keys. No secret values.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

# Sentinel: sidecar uses the same default as standalone.
_SAME: Any = object()

# Top-level TOML tables of personality/server.toml. Used by
# module_config_from_context so production code does not sniff test dicts.
TOML_SECTIONS: frozenset[str] = frozenset(
    {"meta", "personality", "core", "plugins", "security"}
)


@dataclass(frozen=True)
class KeyDecl:
    """Declaration of one key. Values live in env / TOML / runtime, not here."""

    id: str
    env: Optional[str]
    origin: str  # toml | env | runtime
    default: Any
    default_sidecar: Any = _SAME
    sensitive: bool = False
    runtime: bool = False
    description: str = ""
    toml_path: Optional[tuple[str, ...]] = None

    def default_for(self, *, sidecar: bool) -> Any:
        if sidecar and self.default_sidecar is not _SAME:
            return self.default_sidecar
        return self.default


def _k(
    id: str,
    env: Optional[str],
    origin: str,
    default: Any,
    *,
    default_sidecar: Any = _SAME,
    sensitive: bool = False,
    runtime: bool = False,
    description: str = "",
    toml_path: Optional[tuple[str, ...]] = None,
) -> KeyDecl:
    return KeyDecl(
        id=id,
        env=env,
        origin=origin,
        default=default,
        default_sidecar=default_sidecar,
        sensitive=sensitive,
        runtime=runtime,
        description=description,
        toml_path=toml_path,
    )


# Philosophy: .env.example. Declares that a key exists, where it comes from,
# who wins per mode, and whether it is sensitive. Runtime-born values
# (free port, generated API key, user dirs, parent PID) have runtime=True
# and no static sidecar default.
CATALOG: tuple[KeyDecl, ...] = (
    _k("server_host", "NEXE_SERVER_HOST", "env", "127.0.0.1",
       description="Bind host", toml_path=("core", "server", "host")),
    _k("server_port", "NEXE_SERVER_PORT", "env", 9119,
       description="Bind port (standalone). Sidecar uses NEXE_PORT (runtime).",
       toml_path=("core", "server", "port")),
    _k("port", "NEXE_PORT", "runtime", None, runtime=True,
       description="Ephemeral port injected by Tauri at spawn"),
    _k("env", "NEXE_ENV", "env", "development", default_sidecar="production",
       description="production|development", toml_path=("core", "environment", "mode")),
    _k("sidecar", "NEXE_SIDECAR", "runtime", False, runtime=True,
       description="1 when running as the nexe-app sidecar"),
    _k("home", "NEXE_HOME", "runtime", None, runtime=True,
       description="Code root injected by Tauri"),
    _k("data_dir", "NEXE_DATA_DIR", "runtime", None, runtime=True,
       description="User data dir injected by Tauri"),
    _k("logs_dir", "NEXE_LOGS_DIR", "runtime", None, runtime=True,
       description="Logs dir; standalone falls back to ~/.nexe/logs"),
    _k("cache_dir", "NEXE_CACHE_DIR", "runtime", None, runtime=True,
       description="Cache dir; standalone falls back to ~/.nexe/cache"),
    _k("parent_pid", "NEXE_PARENT_PID", "runtime", None, runtime=True,
       description="Tauri parent PID for the watchdog"),
    _k("primary_api_key", "NEXE_PRIMARY_API_KEY", "env", "",
       sensitive=True, description="Primary API key"),
    _k("admin_api_key", "NEXE_ADMIN_API_KEY", "env", None,
       sensitive=True, description="Admin API key"),
    _k("csrf_secret", "NEXE_CSRF_SECRET", "env", None,
       sensitive=True, description="CSRF signing secret"),
    _k("master_key", "NEXE_MASTER_KEY", "env", None,
       sensitive=True, description="HKDF master key"),
    _k("approved_modules", "NEXE_APPROVED_MODULES", "env", None,
       description="Comma-separated module allowlist (required in production)"),
    _k("localhost_aliases", "NEXE_LOCALHOST_ALIASES", "env",
       "127.0.0.1,::1,localhost",
       description="Client IPs treated as localhost by the bootstrap endpoint"),
    _k("trusted_hosts", "NEXE_TRUSTED_HOSTS", "env",
       "127.0.0.1,::1,localhost",
       description="Host headers accepted by TrustedHostMiddleware"),
    _k("encryption_enabled", "NEXE_ENCRYPTION_ENABLED", "env", "auto",
       description="true|false|auto"),
    _k("lang", "NEXE_LANG", "env", "en", description="ca|es|en"),
    _k("default_model", "NEXE_DEFAULT_MODEL", "env", "",
       description="Default chat model"),
    _k("model_engine", "NEXE_MODEL_ENGINE", "env", None,
       description="ollama|mlx|llama_cpp"),
    _k("prompt_tier", "NEXE_PROMPT_TIER", "env", "full",
       description="full|compact"),
    _k("ollama_host", "NEXE_OLLAMA_HOST", "env", "http://localhost:11434",
       description="Ollama URL"),
    _k("qdrant_path", "NEXE_QDRANT_PATH", "env", "storage/vectors",
       default_sidecar=None, runtime=True,
       description="Embedded Qdrant path. Sidecar: {data_dir}/vectors (runtime)."),
    _k("qdrant_url", "NEXE_QDRANT_URL", "env", None,
       description="External Qdrant URL; embedded if unset"),
    _k("auto_ingest_knowledge", "NEXE_AUTO_INGEST_KNOWLEDGE", "env", True,
       default_sidecar=False,
       description="Standalone default ON; sidecar default OFF (onboarding owns ingest)."),
    _k("bootstrap_ttl", "NEXE_BOOTSTRAP_TTL", "env", 30,
       description="Bootstrap token TTL in minutes"),
    _k("bootstrap_display", "NEXE_BOOTSTRAP_DISPLAY", "env", True,
       description="Print bootstrap token to the console"),
    _k("host_alias", "NEXE_HOST", "env", "127.0.0.1",
       description="Alias of NEXE_SERVER_HOST used by the sidecar"),
    _k("memory_read_timeout", "NEXE_MEMORY_READ_TIMEOUT", "env", 8.0,
       description="Seconds a memory/RAG READ may take before it gives up (#890)"),
    _k("state_watcher_interval", "NEXE_STATE_WATCHER_INTERVAL", "env", 30.0,
       description="Seconds between operational-state rounds; 0 disables the watcher"),
    _k("state_watcher_confirmations", "NEXE_STATE_WATCHER_CONFIRMATIONS", "env", 2,
       description="Equal readings needed before a new state is believed (anti-flap)"),
    _k("state_watcher_sensor_timeout", "NEXE_STATE_WATCHER_SENSOR_TIMEOUT", "env", 5.0,
       description="Seconds one sensor may take before the round stops waiting for it (#944)"),
)


_BY_ID: dict[str, KeyDecl] = {k.id: k for k in CATALOG}
_BY_ENV: dict[str, KeyDecl] = {k.env: k for k in CATALOG if k.env}


def get_decl(key_id: str) -> KeyDecl:
    try:
        return _BY_ID[key_id]
    except KeyError as exc:
        raise KeyError(f"config catalog has no key {key_id!r}") from exc


def by_env(name: str) -> Optional[KeyDecl]:
    return _BY_ENV.get(name)


def default_for(key_id: str, *, sidecar: bool = False) -> Any:
    return get_decl(key_id).default_for(sidecar=sidecar)


def is_sensitive(env_or_id: str) -> bool:
    decl = _BY_ID.get(env_or_id) or _BY_ENV.get(env_or_id)
    return bool(decl and decl.sensitive)
