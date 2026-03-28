"""
Tests for crypto integration with downstream components.
"""
import os
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from core.lifespan import ServerState


class TestPersistenceManagerCrypto:
    """PersistenceManager receives crypto_provider from server_state."""

    def test_persistence_accepts_crypto_provider(self, tmp_path):
        """PersistenceManager constructor accepts crypto_provider kwarg."""
        from memory.memory.engines.persistence import PersistenceManager

        mock_crypto = MagicMock()
        pm = PersistenceManager(
            db_path=tmp_path / "test.db",
            qdrant_path=tmp_path / "qdrant",
            collection_name="test",
            vector_size=384,
            crypto_provider=mock_crypto
        )
        assert pm._crypto is mock_crypto

    def test_persistence_none_crypto_by_default(self, tmp_path):
        """PersistenceManager works without crypto (backwards compat)."""
        from memory.memory.engines.persistence import PersistenceManager

        pm = PersistenceManager(
            db_path=tmp_path / "test.db",
            qdrant_path=tmp_path / "qdrant",
            collection_name="test",
            vector_size=384,
        )
        assert pm._crypto is None


class TestSessionManagerCrypto:
    """SessionManager receives crypto_provider."""

    def test_session_manager_accepts_crypto(self, tmp_path):
        """SessionManager constructor accepts crypto_provider kwarg."""
        from plugins.web_ui_module.core.session_manager import SessionManager

        mock_crypto = MagicMock()
        sm = SessionManager(
            storage_path=str(tmp_path / "sessions"),
            crypto_provider=mock_crypto
        )
        assert sm._crypto is mock_crypto

    def test_session_manager_none_crypto_default(self, tmp_path):
        """SessionManager works without crypto (backwards compat)."""
        from plugins.web_ui_module.core.session_manager import SessionManager

        sm = SessionManager(storage_path=str(tmp_path / "sessions"))
        assert sm._crypto is None


class TestDefaultConfigSecurity:
    """Verify security config defaults."""

    def test_default_config_has_security(self):
        from core.config import DEFAULT_CONFIG
        assert 'security' in DEFAULT_CONFIG
        assert 'encryption' in DEFAULT_CONFIG['security']
        assert DEFAULT_CONFIG['security']['encryption']['enabled'] is False
        assert DEFAULT_CONFIG['security']['encryption']['warn_unencrypted'] is True
