"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/plugins/security/test_auth_bypass_warning_reaches_auth_config.py
Description: The boot-time auth-bypass warning and the auth_config health check
    must reach the real auth config. #869 moved auth_config from
    plugins/security/core/ to core/security/ and left both call sites importing
    the old relative path, so every startup logged "Could not evaluate auth
    bypass status" instead: the warning could never fire and the health check
    was permanently in error. Both paths are exercised here, not just imported.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import asyncio
import logging

from plugins.security.module import SecurityModule


class _Keys:
    def __init__(self, valid: bool):
        self.has_any_valid_key = valid


def test_bypass_warning_actually_fires_when_dev_mode_has_no_key(monkeypatch, caplog):
    """Dev mode + no valid key must print the bypass banner.

    The regression this guards is silent: the import error was swallowed by a
    bare `except`, so a live auth bypass logged nothing about auth at all.
    """
    monkeypatch.setattr("core.security.auth_config.is_dev_mode", lambda: True)
    monkeypatch.setattr("core.security.auth_config.load_api_keys", lambda: _Keys(False))
    monkeypatch.delenv("NEXE_DEV_MODE_ALLOW_REMOTE", raising=False)

    with caplog.at_level(logging.WARNING):
        SecurityModule()._warn_if_auth_bypass_active()

    assert "AUTHENTICATION IS IN BYPASS" in caplog.text
    assert "Could not evaluate auth bypass status" not in caplog.text


def test_bypass_warning_stays_quiet_when_a_key_is_configured(monkeypatch, caplog):
    """The twin case: a configured key must not raise the banner."""
    monkeypatch.setattr("core.security.auth_config.is_dev_mode", lambda: True)
    monkeypatch.setattr("core.security.auth_config.load_api_keys", lambda: _Keys(True))

    with caplog.at_level(logging.WARNING):
        SecurityModule()._warn_if_auth_bypass_active()

    assert "AUTHENTICATION IS IN BYPASS" not in caplog.text
    assert "Could not evaluate auth bypass status" not in caplog.text


def test_auth_config_health_check_reports_key_state_not_an_import_error():
    """The auth_config check must report real key state.

    With the stale import it answered `error: No module named ...` on every
    call, which made the whole security module permanently DEGRADED and hid
    any genuine auth-config problem behind an identical message.
    """
    module = SecurityModule()
    module._initialized = True

    result = asyncio.run(module.health_check())
    check = next(c for c in result.checks if c["name"] == "auth_config")

    assert check["status"] in ("ok", "warning"), check
    assert "No module named" not in check["message"]
