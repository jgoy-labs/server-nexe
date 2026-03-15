"""
Conftest per tests de simple_embedder.
Pre-mockeja sentence_transformers si no està disponible (incompatibilitat huggingface-hub).
"""
import sys
from unittest.mock import MagicMock

try:
    import sentence_transformers  # noqa: F401
except (ImportError, Exception):
    mock_st = MagicMock()
    sys.modules["sentence_transformers"] = mock_st
    # Invalidar cache del mòdul si ja s'ha importat parcialment
    for key in list(sys.modules.keys()):
        if key.startswith("memory.embeddings.simple_embedder"):
            del sys.modules[key]
