"""
Tests P1-D — Encryption default 'auto' en lloc de False.

Problema: el default era false — totes les sessions en plain text,
contradient el missatge "privacy-first" del README.

Fix: default 'auto' — si sqlcipher3 disponible: activa encryption;
si no: continua en plain text amb WARNING explícit.

Helper testejable: _resolve_encryption_enabled(env_value, sqlcipher_available) → bool

www.jgoy.net · https://server-nexe.org
"""

import pytest

try:
    from core.lifespan import _resolve_encryption_enabled
except ImportError:
    pytest.skip("_resolve_encryption_enabled helper not available", allow_module_level=True)


class TestResolveEncryptionEnabled:
    def test_auto_with_sqlcipher_enables(self):
        """auto + sqlcipher3 disponible → encryption activa."""
        assert _resolve_encryption_enabled("auto", sqlcipher_available=True) is True

    def test_auto_without_sqlcipher_disabled(self):
        """auto + sqlcipher3 absent → encryption inactiva."""
        assert _resolve_encryption_enabled("auto", sqlcipher_available=False) is False

    def test_empty_string_behaves_as_auto_with_sqlcipher(self):
        """Cadena buida ('' = cas legacy) → comportament auto: ON si disponible."""
        assert _resolve_encryption_enabled("", sqlcipher_available=True) is True

    def test_empty_string_behaves_as_auto_without_sqlcipher(self):
        """Cadena buida → comportament auto: OFF si no disponible."""
        assert _resolve_encryption_enabled("", sqlcipher_available=False) is False

    def test_true_enables_regardless_sqlcipher(self):
        """true → encryption activa (SQLCIPHER_AVAILABLE no importa aquí, el gestiona el caller)."""
        assert _resolve_encryption_enabled("true", sqlcipher_available=True) is True
        assert _resolve_encryption_enabled("true", sqlcipher_available=False) is True

    def test_false_disables(self):
        """false → encryption inactiva independentment de sqlcipher3."""
        assert _resolve_encryption_enabled("false", sqlcipher_available=True) is False
        assert _resolve_encryption_enabled("false", sqlcipher_available=False) is False

    def test_uppercase_true(self):
        """TRUE (majúscules) → tractament equivalent a 'true'."""
        assert _resolve_encryption_enabled("TRUE", sqlcipher_available=True) is True

    def test_uppercase_false(self):
        """FALSE (majúscules) → tractament equivalent a 'false'."""
        assert _resolve_encryption_enabled("FALSE", sqlcipher_available=True) is False

    def test_unknown_value_defaults_off(self):
        """Valor desconegut → OFF (comportament segur per defecte)."""
        assert _resolve_encryption_enabled("maybe", sqlcipher_available=True) is False
