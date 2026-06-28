"""
────────────────────────────────────
Server Nexe
Location: tests/fixos/test_B199.py
Description: TDD fix for B199 — client_delete try/except idèntic = retry no-op.
────────────────────────────────────
"""

from unittest.mock import MagicMock, patch
import pytest


def _make_adapter():
    """Return a QdrantAdapter with a mocked _require_client."""
    from memory.embeddings.adapters.qdrant_adapter import QdrantAdapter

    adapter = QdrantAdapter.__new__(QdrantAdapter)
    return adapter


def test_client_delete_calls_delete_once_on_success():
    """B199 (positiu): delete cridada exactament una vegada quan no hi ha error."""
    adapter = _make_adapter()

    mock_client = MagicMock()
    adapter._require_client = MagicMock(return_value=mock_client)

    from qdrant_client.models import PointIdsList
    selector = PointIdsList(points=["abc"])
    adapter.client_delete("col", selector)

    mock_client.delete.assert_called_once_with(
        collection_name="col",
        points_selector=selector,
    )


def test_client_delete_propagates_exception_without_retry():
    """B199 (negatiu): si delete llança, l'excepció arriba al caller sense retry."""
    adapter = _make_adapter()

    mock_client = MagicMock()
    mock_client.delete.side_effect = RuntimeError("qdrant down")
    adapter._require_client = MagicMock(return_value=mock_client)

    from qdrant_client.models import PointIdsList
    selector = PointIdsList(points=["abc"])

    with pytest.raises(RuntimeError, match="qdrant down"):
        adapter.client_delete("col", selector)

    # Exactament UNA crida — no retry silenciós
    assert mock_client.delete.call_count == 1
