"""
Tests for encryption at-rest integration in lifespan.py
"""
import os
import pytest
from unittest.mock import patch, MagicMock

from core.lifespan import ServerState


class TestServerStateCrypto:
    """crypto_provider attribute on ServerState."""

    def test_crypto_provider_default_none(self):
        state = ServerState()
        assert state.crypto_provider is None

    def test_crypto_provider_assignable(self):
        state = ServerState()
        mock_crypto = MagicMock()
        state.crypto_provider = mock_crypto
        assert state.crypto_provider is mock_crypto
