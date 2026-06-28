"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/tests/test_env_utils.py
Description: Tests for core/env_utils.py — the canonical NEXE_* boolean parser
    (MC-088). Behaviour spec + a completeness guard that the env-bool flags
    route through parse_truthy instead of ad-hoc .lower() == "true".

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import inspect
import pytest

from core.env_utils import parse_port, parse_truthy


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "True", "yes", "YES",
                                   "on", "y", "t", " 1 ", "  TRUE  "])
def test_truthy_values(value):
    assert parse_truthy(value) is True


@pytest.mark.parametrize("value", [None, "", "0", "false", "FALSE", "no", "off",
                                   "n", "f", "nope", "  ", "2", "enabled"])
def test_falsy_values(value):
    assert parse_truthy(value) is False


# MC-088: every NEXE_* boolean flag must go through parse_truthy so they all
# accept the same spellings. This guard fails if any of these call sites
# reintroduces the ad-hoc `.lower() == "true"` env-bool anti-pattern.
@pytest.mark.parametrize("module_path", [
    "core.app",
    "core.lifespan_services",
    "core.lifespan_tokens",
    "core.lifespan",
    "core.lifespan_auto_clean",
    "core.lifespan_modules",
])
def test_no_adhoc_env_bool_parsing(module_path):
    import importlib
    src = inspect.getsource(importlib.import_module(module_path))
    assert '.lower() == "true"' not in src
    assert ".lower() == 'true'" not in src


# MC-087: crypto/keys and server/factory must read NEXE_SIDECAR with the SAME
# truthy parsing as SidecarConfig, so no spelling (true/yes/...) can half-enable
# sidecar mode (crypto CRY-01 skipped vs CSP relaxed). Before the fix they used
# an exact `== "1"` that diverged from SidecarConfig._parse_truthy.
@pytest.mark.parametrize("val,expected", [
    ("1", True), ("true", True), ("TRUE", True), ("yes", True), (" on ", True),
    ("0", False), ("false", False), ("", False), (None, False),
])
def test_is_sidecar_unified_parsing(val, expected, monkeypatch):
    if val is None:
        monkeypatch.delenv("NEXE_SIDECAR", raising=False)
    else:
        monkeypatch.setenv("NEXE_SIDECAR", val)
    from core.crypto.keys import _is_sidecar
    assert _is_sidecar() is expected


def test_factory_uses_unified_sidecar_parsing():
    import core.server.factory as fac
    assert 'os.environ.get("NEXE_SIDECAR") == "1"' not in inspect.getsource(fac)


# ─── MC-093: port parsing + range validation (fail-fast) ───────────────────
@pytest.mark.parametrize("value,expected", [
    ("8080", 8080), ("1", 1), ("65535", 65535), (" 5000 ", 5000),
    (None, None), ("", None), ("   ", None),
])
def test_parse_port_valid(value, expected):
    assert parse_port(value, var_name="NEXE_PORT") == expected


@pytest.mark.parametrize("bad", ["0", "65536", "99999", "-1", "abc", "80.5", "8o80"])
def test_parse_port_invalid_raises(bad):
    with pytest.raises(ValueError) as exc:
        parse_port(bad, var_name="NEXE_PORT")
    assert "NEXE_PORT" in str(exc.value)  # error names the offending var


def test_config_env_override_rejects_out_of_range_port(monkeypatch):
    # MC-093: NEXE_SERVER_PORT must fail fast on an out-of-range value instead of
    # silently passing it to uvicorn (which crashes cryptically later).
    from core.config import _apply_env_overrides
    monkeypatch.setenv("NEXE_SERVER_PORT", "99999")
    with pytest.raises(ValueError):
        _apply_env_overrides({"core": {"server": {}}})


def test_config_env_override_accepts_valid_port(monkeypatch):
    from core.config import _apply_env_overrides
    monkeypatch.setenv("NEXE_SERVER_PORT", "9000")
    merged = _apply_env_overrides({"core": {"server": {}}})
    assert merged["core"]["server"]["port"] == 9000
