"""
Conftest per tests de simple_embedder.
Pre-mockeja fastembed si no està disponible.
"""
import sys
from unittest.mock import MagicMock

try:
    import fastembed  # noqa: F401
except (ImportError, Exception):
    mock_fe = MagicMock()
    sys.modules["fastembed"] = mock_fe
    # Invalidar cache del mòdul si ja s'ha importat parcialment
    for key in list(sys.modules.keys()):
        if key.startswith("memory.embeddings.simple_embedder"):
            del sys.modules[key]
