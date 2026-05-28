"""F2.1 Sessió 1 — Tests TDD per a core/sidecar_config.SidecarConfig.

These tests act as the SPECIFICATION of SidecarConfig.from_env() behavior.
Implementation: core/sidecar_config.py.

Run: pytest tests/core/test_sidecar_config.py -v --no-cov
"""

from __future__ import annotations

import os
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from core.sidecar_config import (
    DEFAULT_TRUSTED_HOSTS,
    SIDECAR_CORS_ORIGINS,
    SIDECAR_REQUIRED_ENV_VARS,
    SidecarConfig,
    SidecarConfigError,
    get_sidecar_config,
    reset_sidecar_config,
)


# ─────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────


@pytest.fixture
def clean_env(monkeypatch):
    """Strip all NEXE_* env vars for test isolation using monkeypatch.

    Pytest's monkeypatch.delenv() auto-restores at teardown — no manual save/restore
    needed. Also ensures any NEXE_* added during the test via monkeypatch.setenv()
    is automatically cleaned up.

    NOTE: tests must use `monkeypatch.setenv(...)` (or `os.environ` directly + manual
    cleanup) — see fixture-level cleanup loop below for the latter case.
    """
    # Snapshot + delete all NEXE_* present at setup (monkeypatch auto-restores).
    nexe_keys = [k for k in list(os.environ) if k.startswith("NEXE_")]
    for k in nexe_keys:
        monkeypatch.delenv(k, raising=False)
    reset_sidecar_config()
    yield
    # Belt + suspenders: pop any NEXE_* added via direct os.environ assignment
    # (not via monkeypatch). This is needed because some tests set vars directly
    # via os.environ["NEXE_X"] = "y" instead of monkeypatch.setenv().
    for k in [k for k in list(os.environ) if k.startswith("NEXE_")]:
        os.environ.pop(k, None)
    reset_sidecar_config()


@pytest.fixture
def sidecar_env(monkeypatch, clean_env):
    """Set all required sidecar env vars via monkeypatch; yields dict for further patching.

    Auto-cleanup at teardown via monkeypatch + clean_env's belt-and-suspenders loop.
    """
    env = {
        "NEXE_SIDECAR": "1",
        "NEXE_ENV": "production",
        "NEXE_HOME": "/tmp/nexe-test/app",
        "NEXE_PRIMARY_API_KEY": "test-key-abc123",
        "NEXE_PORT": "59999",
        "NEXE_DATA_DIR": "/tmp/nexe-test/data",
        "NEXE_LOGS_DIR": "/tmp/nexe-test/logs",
        "NEXE_PARENT_PID": "12345",
    }
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    reset_sidecar_config()
    yield env


# ─────────────────────────────────────────────────────────────────────
# Esquema (camps obligatoris presents) — TDD spec
# ─────────────────────────────────────────────────────────────────────


def test_sidecar_config_has_required_fields():
    """SidecarConfig must expose exactly the expected fields."""
    expected = {
        "is_sidecar", "is_production",
        "home_dir", "logs_dir", "data_dir", "cache_dir", "vectors_dir",
        "host", "port", "cors_origins", "trusted_hosts",
        "api_key", "parent_pid", "approved_modules",
        "default_model", "model_engine", "prompt_tier", "lang",
        # Services (Turing #3)
        "ollama_host", "qdrant_url", "csrf_secret", "encryption_enabled",
        "auto_ingest_knowledge", "bootstrap_ttl",
    }
    actual = set(SidecarConfig.__dataclass_fields__)
    assert expected == actual, f"Diff: {expected ^ actual}"


def test_sidecar_config_is_frozen(clean_env):
    """SidecarConfig must be immutable after construction."""
    config = SidecarConfig.from_env()
    with pytest.raises(FrozenInstanceError):
        config.is_sidecar = not config.is_sidecar  # type: ignore[misc]


def test_sidecar_config_path_fields_are_path_instances(clean_env):
    """All path fields must be pathlib.Path instances."""
    config = SidecarConfig.from_env()
    assert isinstance(config.home_dir, Path)
    assert isinstance(config.logs_dir, Path)
    assert isinstance(config.data_dir, Path)
    assert isinstance(config.cache_dir, Path)
    assert isinstance(config.vectors_dir, Path)


def test_sidecar_config_tuple_fields_are_tuples(clean_env):
    """cors_origins, trusted_hosts, approved_modules must be tuples (immutable)."""
    config = SidecarConfig.from_env()
    assert isinstance(config.cors_origins, tuple)
    assert isinstance(config.trusted_hosts, tuple)
    assert isinstance(config.approved_modules, tuple)


# ─────────────────────────────────────────────────────────────────────
# Standalone mode (NO NEXE_SIDECAR)
# ─────────────────────────────────────────────────────────────────────


def test_standalone_mode_is_sidecar_false(clean_env):
    """Without NEXE_SIDECAR, is_sidecar=False."""
    config = SidecarConfig.from_env()
    assert config.is_sidecar is False


def test_standalone_mode_is_production_false_default(clean_env):
    """Standalone defaults to development (is_production=False)."""
    config = SidecarConfig.from_env()
    assert config.is_production is False


def test_standalone_mode_defaults_host_port(clean_env):
    """Standalone uses 127.0.0.1:9119 as defaults."""
    config = SidecarConfig.from_env()
    assert config.host == "127.0.0.1"
    assert config.port == 9119


def test_standalone_mode_no_fail_fast(clean_env):
    """Standalone tolerates missing NEXE_* required vars (no fail-fast)."""
    # No env vars set → must NOT raise
    config = SidecarConfig.from_env()
    assert config.is_sidecar is False


def test_standalone_mode_api_key_empty(clean_env):
    """Standalone without NEXE_PRIMARY_API_KEY → empty string."""
    config = SidecarConfig.from_env()
    assert config.api_key == ""


# ─────────────────────────────────────────────────────────────────────
# Sidecar mode (NEXE_SIDECAR=1)
# ─────────────────────────────────────────────────────────────────────


def test_sidecar_mode_with_all_required(sidecar_env):
    """With all required env vars, SidecarConfig builds correctly."""
    config = SidecarConfig.from_env()
    assert config.is_sidecar is True
    assert config.is_production is True
    assert config.home_dir == Path("/tmp/nexe-test/app")
    assert config.data_dir == Path("/tmp/nexe-test/data")
    assert config.logs_dir == Path("/tmp/nexe-test/logs")
    assert config.port == 59999
    assert config.api_key == "test-key-abc123"
    assert config.parent_pid == 12345


@pytest.mark.parametrize("missing_var", SIDECAR_REQUIRED_ENV_VARS)
def test_sidecar_mode_fail_fast_missing_required(sidecar_env, missing_var):
    """Sidecar mode raises SidecarConfigError when any required var is missing."""
    os.environ.pop(missing_var, None)
    reset_sidecar_config()
    with pytest.raises(SidecarConfigError) as exc_info:
        SidecarConfig.from_env()
    assert missing_var in str(exc_info.value)


def test_sidecar_mode_production_implicit_when_env_unset(sidecar_env):
    """is_sidecar=True without NEXE_ENV defaults to is_production=True."""
    os.environ.pop("NEXE_ENV", None)
    reset_sidecar_config()
    config = SidecarConfig.from_env()
    assert config.is_production is True


def test_sidecar_mode_can_override_env_development(sidecar_env):
    """Even with NEXE_SIDECAR=1, NEXE_ENV=development is honored."""
    os.environ["NEXE_ENV"] = "development"
    reset_sidecar_config()
    config = SidecarConfig.from_env()
    assert config.is_sidecar is True
    assert config.is_production is False


# ─────────────────────────────────────────────────────────────────────
# CORS origins (camp computat — resol A8 BUG-NX-1)
# ─────────────────────────────────────────────────────────────────────


def test_cors_origins_includes_tauri_when_sidecar(sidecar_env):
    """is_sidecar=True → cors_origins MUST include all Tauri origins.

    This is the FIX for anomalia A8 (BUG-NX-1) from F1-smoke/resultats.md:
    the old hard-coded list at core/middleware.py didn't include
    tauri://localhost nor http://localhost:1420.
    """
    config = SidecarConfig.from_env()
    for origin in SIDECAR_CORS_ORIGINS:
        assert origin in config.cors_origins, f"Missing Tauri origin: {origin}"


def test_cors_origins_excludes_tauri_when_standalone(clean_env):
    """is_sidecar=False → cors_origins MUST NOT include Tauri origins."""
    config = SidecarConfig.from_env()
    for origin in SIDECAR_CORS_ORIGINS:
        assert origin not in config.cors_origins, f"Standalone leaked: {origin}"


def test_cors_origins_includes_current_port(sidecar_env):
    """cors_origins MUST include http://localhost:<port> for the active port."""
    config = SidecarConfig.from_env()
    assert f"http://localhost:{config.port}" in config.cors_origins
    assert f"http://127.0.0.1:{config.port}" in config.cors_origins


def test_cors_origins_dynamic_with_different_port(clean_env):
    """Changing NEXE_PORT updates the port-specific CORS entries."""
    os.environ["NEXE_PORT"] = "12345"
    reset_sidecar_config()
    config = SidecarConfig.from_env()
    assert "http://localhost:12345" in config.cors_origins


# ─────────────────────────────────────────────────────────────────────
# Trusted hosts (camp computat)
# ─────────────────────────────────────────────────────────────────────


def test_trusted_hosts_default(clean_env):
    """No NEXE_LOCALHOST_ALIASES → defaults: 127.0.0.1, ::1, localhost."""
    config = SidecarConfig.from_env()
    assert config.trusted_hosts == DEFAULT_TRUSTED_HOSTS


def test_trusted_hosts_custom_via_env(clean_env):
    """NEXE_LOCALHOST_ALIASES parsed as comma-separated tuple."""
    os.environ["NEXE_LOCALHOST_ALIASES"] = "127.0.0.1,mylocal,foo.local"
    reset_sidecar_config()
    config = SidecarConfig.from_env()
    assert config.trusted_hosts == ("127.0.0.1", "mylocal", "foo.local")


def test_trusted_hosts_strips_whitespace(clean_env):
    """Whitespace around comma-separated aliases is stripped."""
    os.environ["NEXE_LOCALHOST_ALIASES"] = " 127.0.0.1 , localhost , foo "
    reset_sidecar_config()
    config = SidecarConfig.from_env()
    assert config.trusted_hosts == ("127.0.0.1", "localhost", "foo")


def test_trusted_hosts_ignores_empty_entries(clean_env):
    """Empty entries (",, ,") are filtered out."""
    os.environ["NEXE_LOCALHOST_ALIASES"] = "127.0.0.1,,localhost,"
    reset_sidecar_config()
    config = SidecarConfig.from_env()
    assert "" not in config.trusted_hosts
    assert "127.0.0.1" in config.trusted_hosts
    assert "localhost" in config.trusted_hosts


# ─────────────────────────────────────────────────────────────────────
# Approved modules (allowlist)
# ─────────────────────────────────────────────────────────────────────


def test_approved_modules_parsed_as_tuple(clean_env):
    """NEXE_APPROVED_MODULES parsed as comma-separated tuple."""
    os.environ["NEXE_APPROVED_MODULES"] = "security,memory,rag"
    reset_sidecar_config()
    config = SidecarConfig.from_env()
    assert config.approved_modules == ("security", "memory", "rag")


def test_approved_modules_empty_default(clean_env):
    """No NEXE_APPROVED_MODULES → empty tuple."""
    config = SidecarConfig.from_env()
    assert config.approved_modules == ()


def test_approved_modules_strips_whitespace(clean_env):
    """Whitespace around module names is stripped."""
    os.environ["NEXE_APPROVED_MODULES"] = " security , memory , rag "
    reset_sidecar_config()
    config = SidecarConfig.from_env()
    assert config.approved_modules == ("security", "memory", "rag")


# ─────────────────────────────────────────────────────────────────────
# Parent PID (Tauri watchdog)
# ─────────────────────────────────────────────────────────────────────


def test_parent_pid_parsed_as_int(sidecar_env):
    """NEXE_PARENT_PID parsed as int."""
    config = SidecarConfig.from_env()
    assert config.parent_pid == 12345


def test_parent_pid_none_when_unset(clean_env):
    """Standalone (no NEXE_PARENT_PID) → parent_pid=None."""
    config = SidecarConfig.from_env()
    assert config.parent_pid is None


def test_parent_pid_invalid_returns_none(clean_env):
    """Non-integer NEXE_PARENT_PID → None (no crash, watchdog skips)."""
    os.environ["NEXE_PARENT_PID"] = "not-a-pid"
    reset_sidecar_config()
    config = SidecarConfig.from_env()
    assert config.parent_pid is None


# ─────────────────────────────────────────────────────────────────────
# Port parsing (edge cases)
# ─────────────────────────────────────────────────────────────────────


def test_port_invalid_raises(clean_env):
    """Non-integer NEXE_PORT raises SidecarConfigError (fail-fast)."""
    os.environ["NEXE_PORT"] = "not-a-number"
    reset_sidecar_config()
    with pytest.raises(SidecarConfigError) as exc_info:
        SidecarConfig.from_env()
    assert "NEXE_PORT" in str(exc_info.value) or "NEXE_SERVER_PORT" in str(exc_info.value)


def test_port_nexe_server_port_fallback(clean_env):
    """If NEXE_PORT unset, NEXE_SERVER_PORT is used."""
    os.environ["NEXE_SERVER_PORT"] = "8765"
    reset_sidecar_config()
    config = SidecarConfig.from_env()
    assert config.port == 8765


def test_port_nexe_port_priority(clean_env):
    """NEXE_PORT takes priority over NEXE_SERVER_PORT."""
    os.environ["NEXE_PORT"] = "1234"
    os.environ["NEXE_SERVER_PORT"] = "5678"
    reset_sidecar_config()
    config = SidecarConfig.from_env()
    assert config.port == 1234


# ─────────────────────────────────────────────────────────────────────
# Port range validation (Auditor F2.1 S1 — edge cases)
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("invalid_port", ["0", "-1", "1023", "65536", "99999"])
def test_port_out_of_range_raises(clean_env, invalid_port):
    """Ports outside [1024, 65535] raise SidecarConfigError."""
    os.environ["NEXE_PORT"] = invalid_port
    reset_sidecar_config()
    with pytest.raises(SidecarConfigError) as exc_info:
        SidecarConfig.from_env()
    assert "range" in str(exc_info.value) or "out of range" in str(exc_info.value)


def test_port_empty_falls_through_to_server_port(clean_env):
    """Empty NEXE_PORT (not unset) should fall through to NEXE_SERVER_PORT."""
    os.environ["NEXE_PORT"] = ""
    os.environ["NEXE_SERVER_PORT"] = "8765"
    reset_sidecar_config()
    config = SidecarConfig.from_env()
    assert config.port == 8765


def test_port_zero_in_nexe_port_not_fallback(clean_env):
    """NEXE_PORT='0' must FAIL range validation, NOT silently fall through.

    Pre-fix: `or` operator considered '0' falsy and fell through to
    NEXE_SERVER_PORT → port=9119. That was wrong: 0 is an explicit invalid.
    """
    os.environ["NEXE_PORT"] = "0"
    os.environ["NEXE_SERVER_PORT"] = "9119"
    reset_sidecar_config()
    with pytest.raises(SidecarConfigError):
        SidecarConfig.from_env()


# ─────────────────────────────────────────────────────────────────────
# NEXE_SIDECAR truthy parsing (Auditor F2.1 S1 — edge cases)
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("truthy_value", ["1", "true", "TRUE", "True", "yes", "YES", "on", "y", "t", " 1 ", "  TRUE  "])
def test_nexe_sidecar_truthy_values(clean_env, truthy_value):
    """NEXE_SIDECAR accepts common truthy values (case-insensitive, stripped)."""
    os.environ["NEXE_SIDECAR"] = truthy_value
    # Add required vars to avoid fail-fast
    os.environ.update({
        "NEXE_HOME": "/tmp",
        "NEXE_PRIMARY_API_KEY": "k",
        "NEXE_PORT": "8765",
        "NEXE_DATA_DIR": "/tmp",
        "NEXE_LOGS_DIR": "/tmp",
        "NEXE_PARENT_PID": "1",
    })
    reset_sidecar_config()
    config = SidecarConfig.from_env()
    assert config.is_sidecar is True, f"Truthy {truthy_value!r} not recognized"


@pytest.mark.parametrize("falsy_value", ["0", "false", "FALSE", "no", "off", "", "  ", "anything-else"])
def test_nexe_sidecar_falsy_values(clean_env, falsy_value):
    """NEXE_SIDECAR rejects falsy/unknown values (is_sidecar=False)."""
    os.environ["NEXE_SIDECAR"] = falsy_value
    reset_sidecar_config()
    config = SidecarConfig.from_env()
    assert config.is_sidecar is False, f"Falsy {falsy_value!r} treated as truthy"


# ─────────────────────────────────────────────────────────────────────
# NEXE_ENV whitespace + case (Turing recomanació #6)
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("env_value", ["production", "PRODUCTION", "Production", "  production  ", " PRODUCTION "])
def test_nexe_env_production_variants(clean_env, env_value):
    """NEXE_ENV production accepts case-insensitive + whitespace-stripped variants."""
    os.environ["NEXE_ENV"] = env_value
    reset_sidecar_config()
    config = SidecarConfig.from_env()
    assert config.is_production is True, f"NEXE_ENV={env_value!r} not recognized as production"


@pytest.mark.parametrize("env_value", ["development", "DEVELOPMENT", "Development", "  development  ", "dev", "anything"])
def test_nexe_env_non_production_variants(clean_env, env_value):
    """NEXE_ENV non-production values keep is_production=False."""
    os.environ["NEXE_ENV"] = env_value
    reset_sidecar_config()
    config = SidecarConfig.from_env()
    assert config.is_production is False, f"NEXE_ENV={env_value!r} wrongly treated as production"


# ─────────────────────────────────────────────────────────────────────
# Services fields (Turing #3 — expansion per Sessió 3)
# ─────────────────────────────────────────────────────────────────────


def test_ollama_host_default(clean_env):
    """NEXE_OLLAMA_HOST unset → default http://localhost:11434."""
    config = SidecarConfig.from_env()
    assert config.ollama_host == "http://localhost:11434"


def test_ollama_host_custom(clean_env):
    """NEXE_OLLAMA_HOST override usat."""
    os.environ["NEXE_OLLAMA_HOST"] = "http://my-ollama:8080"
    reset_sidecar_config()
    config = SidecarConfig.from_env()
    assert config.ollama_host == "http://my-ollama:8080"


def test_qdrant_url_optional(clean_env):
    """NEXE_QDRANT_URL unset → None (embedded mode)."""
    config = SidecarConfig.from_env()
    assert config.qdrant_url is None


def test_qdrant_url_custom(clean_env):
    """NEXE_QDRANT_URL extern."""
    os.environ["NEXE_QDRANT_URL"] = "http://qdrant:6333"
    reset_sidecar_config()
    config = SidecarConfig.from_env()
    assert config.qdrant_url == "http://qdrant:6333"


def test_csrf_secret_optional(clean_env):
    """NEXE_CSRF_SECRET unset → None (CSRF disabled or session-only)."""
    config = SidecarConfig.from_env()
    assert config.csrf_secret is None


def test_csrf_secret_custom(clean_env):
    """NEXE_CSRF_SECRET valor."""
    os.environ["NEXE_CSRF_SECRET"] = "deadbeef-32-bytes-here"
    reset_sidecar_config()
    config = SidecarConfig.from_env()
    assert config.csrf_secret == "deadbeef-32-bytes-here"


def test_encryption_enabled_default_auto(clean_env):
    """NEXE_ENCRYPTION_ENABLED unset → 'auto' (lifespan_crypto decideix runtime)."""
    config = SidecarConfig.from_env()
    assert config.encryption_enabled == "auto"


@pytest.mark.parametrize("value,expected", [
    ("true", "true"), ("TRUE", "true"), ("True", "true"),
    ("false", "false"), ("FALSE", "false"),
    ("auto", "auto"), ("AUTO", "auto"), ("  Auto  ", "auto"),
])
def test_encryption_enabled_normalized(clean_env, value, expected):
    """NEXE_ENCRYPTION_ENABLED normalitzat a lowercase + stripped."""
    os.environ["NEXE_ENCRYPTION_ENABLED"] = value
    reset_sidecar_config()
    config = SidecarConfig.from_env()
    assert config.encryption_enabled == expected


def test_auto_ingest_knowledge_default_false(clean_env):
    """NEXE_AUTO_INGEST_KNOWLEDGE unset → False."""
    config = SidecarConfig.from_env()
    assert config.auto_ingest_knowledge is False


@pytest.mark.parametrize("value", ["1", "true", "yes", "TRUE"])
def test_auto_ingest_knowledge_truthy(clean_env, value):
    """NEXE_AUTO_INGEST_KNOWLEDGE truthy values."""
    os.environ["NEXE_AUTO_INGEST_KNOWLEDGE"] = value
    reset_sidecar_config()
    config = SidecarConfig.from_env()
    assert config.auto_ingest_knowledge is True


def test_bootstrap_ttl_default_30(clean_env):
    """NEXE_BOOTSTRAP_TTL unset → 30 minuts."""
    config = SidecarConfig.from_env()
    assert config.bootstrap_ttl == 30


def test_bootstrap_ttl_custom(clean_env):
    """NEXE_BOOTSTRAP_TTL int parsing."""
    os.environ["NEXE_BOOTSTRAP_TTL"] = "60"
    reset_sidecar_config()
    config = SidecarConfig.from_env()
    assert config.bootstrap_ttl == 60


def test_bootstrap_ttl_invalid_raises(clean_env):
    """NEXE_BOOTSTRAP_TTL non-int raises SidecarConfigError."""
    os.environ["NEXE_BOOTSTRAP_TTL"] = "not-a-number"
    reset_sidecar_config()
    with pytest.raises(SidecarConfigError):
        SidecarConfig.from_env()


# ─────────────────────────────────────────────────────────────────────
# Engine config
# ─────────────────────────────────────────────────────────────────────


def test_default_model_empty_when_unset(clean_env):
    """No NEXE_DEFAULT_MODEL → empty string."""
    config = SidecarConfig.from_env()
    assert config.default_model == ""


def test_model_engine_optional(clean_env):
    """No NEXE_MODEL_ENGINE → None."""
    config = SidecarConfig.from_env()
    assert config.model_engine is None


def test_lang_default_en(clean_env):
    """No NEXE_LANG → default 'en' (English, international default)."""
    config = SidecarConfig.from_env()
    assert config.lang == "en"


def test_prompt_tier_default_full(clean_env):
    """No NEXE_PROMPT_TIER → 'full' default."""
    config = SidecarConfig.from_env()
    assert config.prompt_tier == "full"


# ─────────────────────────────────────────────────────────────────────
# Singleton get_sidecar_config()
# ─────────────────────────────────────────────────────────────────────


def test_get_sidecar_config_returns_same_instance(clean_env):
    """get_sidecar_config() returns the same instance on repeated calls."""
    config1 = get_sidecar_config()
    config2 = get_sidecar_config()
    assert config1 is config2


def test_reset_sidecar_config_forces_rebuild(clean_env):
    """reset_sidecar_config() forces from_env() to rebuild on next call."""
    config1 = get_sidecar_config()
    reset_sidecar_config()
    config2 = get_sidecar_config()
    assert config1 is not config2


def test_singleton_picks_up_env_changes_after_reset(clean_env):
    """After reset, get_sidecar_config() reflects new env vars."""
    config1 = get_sidecar_config()
    assert config1.port == 9119  # default

    os.environ["NEXE_PORT"] = "8888"
    # WITHOUT reset, singleton still returns the cached version
    config_cached = get_sidecar_config()
    assert config_cached.port == 9119
    assert config_cached is config1

    reset_sidecar_config()
    config2 = get_sidecar_config()
    assert config2.port == 8888
