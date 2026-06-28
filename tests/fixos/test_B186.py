"""
────────────────────────────────────
Server Nexe
Location: tests/fixos/test_B186.py
Description: TDD fix for B186 — _get_file_rag() empassa TOTS els errors a None.
────────────────────────────────────
"""

from unittest.mock import patch

import pytest


def test_get_file_rag_returns_none_on_import_error():
    """B186 (ImportError): mòdul absent → None sense excepció."""
    import memory.rag.routers.endpoints as ep

    with patch("memory.rag.module.get_file_rag", side_effect=ImportError("no module")):
        result = ep._get_file_rag()
    assert result is None


def test_get_file_rag_propagates_runtime_error():
    """B186 (RuntimeError): error de runtime → ha de propagar, NO retornar None."""
    import memory.rag.routers.endpoints as ep

    with patch("memory.rag.module.get_file_rag", side_effect=RuntimeError("qdrant crash")):
        with pytest.raises(RuntimeError, match="qdrant crash"):
            ep._get_file_rag()
