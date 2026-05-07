"""
Tests P1-D — Encryption default 'auto' instead of False.

Problem: the default was false — all sessions in plain text,
contradicting the "privacy-first" message in the README.

Fix: default 'auto' — if sqlcipher3 is available: enable encryption;
if not: continue in plain text with an explicit WARNING.

Testable helper: _resolve_encryption_enabled(env_value, sqlcipher_available) → bool

www.jgoy.net · https://server-nexe.org
"""

import pytest

try:
    from core.lifespan import _resolve_encryption_enabled
except ImportError:
    pytest.skip("_resolve_encryption_enabled helper not available", allow_module_level=True)


class TestResolveEncryptionEnabled:
    def test_auto_with_sqlcipher_enables(self):
        """auto + sqlcipher3 available → encryption enabled."""
        assert _resolve_encryption_enabled("auto", sqlcipher_available=True) is True

    def test_auto_without_sqlcipher_disabled(self):
        """auto + sqlcipher3 absent → encryption disabled."""
        assert _resolve_encryption_enabled("auto", sqlcipher_available=False) is False

    def test_empty_string_behaves_as_auto_with_sqlcipher(self):
        """Empty string ('' = legacy case) → auto behaviour: ON if available."""
        assert _resolve_encryption_enabled("", sqlcipher_available=True) is True

    def test_empty_string_behaves_as_auto_without_sqlcipher(self):
        """Empty string → auto behaviour: OFF if not available."""
        assert _resolve_encryption_enabled("", sqlcipher_available=False) is False

    def test_true_enables_regardless_sqlcipher(self):
        """true → encryption enabled (SQLCIPHER_AVAILABLE doesn't matter here, handled by caller)."""
        assert _resolve_encryption_enabled("true", sqlcipher_available=True) is True
        assert _resolve_encryption_enabled("true", sqlcipher_available=False) is True

    def test_false_disables(self):
        """false → encryption disabled regardless of sqlcipher3."""
        assert _resolve_encryption_enabled("false", sqlcipher_available=True) is False
        assert _resolve_encryption_enabled("false", sqlcipher_available=False) is False

    def test_uppercase_true(self):
        """TRUE (uppercase) → equivalent treatment to 'true'."""
        assert _resolve_encryption_enabled("TRUE", sqlcipher_available=True) is True

    def test_uppercase_false(self):
        """FALSE (uppercase) → equivalent treatment to 'false'."""
        assert _resolve_encryption_enabled("FALSE", sqlcipher_available=True) is False

    def test_unknown_value_defaults_off(self):
        """Unknown value → OFF (safe default behaviour)."""
        assert _resolve_encryption_enabled("maybe", sqlcipher_available=True) is False
