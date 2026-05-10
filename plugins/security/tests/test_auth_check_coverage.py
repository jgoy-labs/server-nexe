"""Tests for plugins/security/checks/auth_check.py — coverage gaps."""
import os
import pytest
from unittest.mock import patch


class TestAuthCheck:
    """Tests for AuthCheck.run()."""

    def test_no_keys_no_dev_mode_critical(self):
        from plugins.security.checks.auth_check import AuthCheck
        env = {
            "NEXE_PRIMARY_API_KEY": "",
            "NEXE_SECONDARY_API_KEY": "",
            "NEXE_ADMIN_API_KEY": "",
            "NEXE_DEV_MODE": "false",
            "NEXE_ENV": "development",
            "NEXE_DEV_MODE_ALLOW_REMOTE": "false",
            "NEXE_APPROVED_MODULES": "",
        }
        with patch.dict(os.environ, env, clear=False):
            findings = AuthCheck().run()
        critical = [f for f in findings if f["severity"] == "CRITICAL"]
        assert len(critical) >= 1
        assert any("No API keys" in f["title"] for f in critical)

    def test_no_keys_dev_mode_high(self):
        from plugins.security.checks.auth_check import AuthCheck
        env = {
            "NEXE_PRIMARY_API_KEY": "",
            "NEXE_SECONDARY_API_KEY": "",
            "NEXE_ADMIN_API_KEY": "",
            "NEXE_DEV_MODE": "true",
            "NEXE_ENV": "development",
            "NEXE_DEV_MODE_ALLOW_REMOTE": "false",
            "NEXE_APPROVED_MODULES": "",
        }
        with patch.dict(os.environ, env, clear=False):
            findings = AuthCheck().run()
        high = [f for f in findings if f["severity"] == "HIGH"]
        assert any("dev mode" in f["title"].lower() for f in high)

    def test_dev_mode_in_production_critical(self):
        from plugins.security.checks.auth_check import AuthCheck
        env = {
            "NEXE_PRIMARY_API_KEY": "test-key",
            "NEXE_SECONDARY_API_KEY": "",
            "NEXE_ADMIN_API_KEY": "",
            "NEXE_DEV_MODE": "true",
            "NEXE_ENV": "production",
            "NEXE_DEV_MODE_ALLOW_REMOTE": "false",
            "NEXE_APPROVED_MODULES": "security",
        }
        with patch.dict(os.environ, env, clear=False):
            findings = AuthCheck().run()
        assert any("production" in f["title"].lower() for f in findings)

    def test_remote_dev_bypass_high(self):
        from plugins.security.checks.auth_check import AuthCheck
        env = {
            "NEXE_PRIMARY_API_KEY": "test-key",
            "NEXE_SECONDARY_API_KEY": "",
            "NEXE_ADMIN_API_KEY": "",
            "NEXE_DEV_MODE": "true",
            "NEXE_ENV": "development",
            "NEXE_DEV_MODE_ALLOW_REMOTE": "true",
            "NEXE_APPROVED_MODULES": "",
        }
        with patch.dict(os.environ, env, clear=False):
            findings = AuthCheck().run()
        assert any("Remote" in f["title"] for f in findings)

    def test_secondary_key_low(self):
        from plugins.security.checks.auth_check import AuthCheck
        env = {
            "NEXE_PRIMARY_API_KEY": "primary",
            "NEXE_SECONDARY_API_KEY": "secondary",
            "NEXE_ADMIN_API_KEY": "",
            "NEXE_DEV_MODE": "false",
            "NEXE_ENV": "development",
            "NEXE_DEV_MODE_ALLOW_REMOTE": "false",
            "NEXE_APPROVED_MODULES": "",
        }
        with patch.dict(os.environ, env, clear=False):
            findings = AuthCheck().run()
        assert any("Secondary" in f["title"] for f in findings)

    def test_no_allowlist_in_production(self):
        from plugins.security.checks.auth_check import AuthCheck
        env = {
            "NEXE_PRIMARY_API_KEY": "key",
            "NEXE_SECONDARY_API_KEY": "",
            "NEXE_ADMIN_API_KEY": "",
            "NEXE_DEV_MODE": "false",
            "NEXE_ENV": "production",
            "NEXE_DEV_MODE_ALLOW_REMOTE": "false",
            "NEXE_APPROVED_MODULES": "",
        }
        with patch.dict(os.environ, env, clear=False):
            findings = AuthCheck().run()
        assert any("allowlist" in f["title"].lower() for f in findings)

    def test_all_good_no_critical(self):
        from plugins.security.checks.auth_check import AuthCheck
        env = {
            "NEXE_PRIMARY_API_KEY": "key",
            "NEXE_SECONDARY_API_KEY": "",
            "NEXE_ADMIN_API_KEY": "",
            "NEXE_DEV_MODE": "false",
            "NEXE_ENV": "development",
            "NEXE_DEV_MODE_ALLOW_REMOTE": "false",
            "NEXE_APPROVED_MODULES": "",
        }
        with patch.dict(os.environ, env, clear=False):
            findings = AuthCheck().run()
        critical = [f for f in findings if f["severity"] == "CRITICAL"]
        assert len(critical) == 0
