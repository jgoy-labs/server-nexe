"""
Conftest for simple_embedder tests.
Pre-mocks fastembed if not available.
"""
import sys
from unittest.mock import MagicMock

try:
    import fastembed  # noqa: F401
except (ImportError, Exception):
    mock_fe = MagicMock()
    sys.modules["fastembed"] = mock_fe
    # Invalidate module cache if already partially imported
    for key in list(sys.modules.keys()):
        if key.startswith("memory.embeddings.simple_embedder"):
            del sys.modules[key]
