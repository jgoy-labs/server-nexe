"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/test_b2_qdrant_filter_privacy.py
Description: TDD cec — B2 privacy leak: search_with_filter drops user_id filter
             in qdrant ≥1.11 fallback path (query_points without query_filter).
             Onada 4.6b / xfail strict pre-fix.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
import importlib.util
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_ADAPTER_FILE = Path(__file__).parents[1] / "memory" / "embeddings" / "adapters" / "qdrant_adapter.py"


def _load_qdrant_adapter():
    spec = importlib.util.spec_from_file_location("_qdrant_adapter_tdd_b2", str(_ADAPTER_FILE))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.QdrantAdapter


def _make_point(user_id: str, content: str) -> MagicMock:
    pt = MagicMock()
    pt.payload = {"user_id": user_id, "content": content}
    return pt


@pytest.mark.xfail(
    strict=True,
    reason=(
        "B2: fallback query_points() drops user_id filter — privacy leak P0. "
        "Quan search() falla (qdrant ≥1.11), el fallback no passa query_filter "
        "i retorna vectors de tots els usuaris. (Onada 4.6b, pre-fix)"
    ),
)
def test_search_with_filter_user_id_drop_in_fallback():
    """Fallback query_points() ha de respectar el user_id filter.

    Post-fix: query_points() ha de rebre query_filter i filtrar correctament.
    Ara: retorna user-A i user-B junts per una query filtrada a user-A.

    Smart mock: simula el comportament real del vector store — sense query_filter
    retorna tots els punts; amb query_filter retorna only el subset filtrat.
    Revert mental: aplicar fix → query_points rep query_filter → test XPASS.
    """
    point_a = _make_point("user-A", "secret of A")
    point_b = _make_point("user-B", "secret of B")

    def _smart_query_points(collection_name, query, limit, query_filter=None, **_kw):
        res = MagicMock()
        # Sense filtre: comportament actual buggy — retorna tots els points
        # Amb filtre: comportament esperat post-fix — retorna sols els filtrats
        res.points = [point_a] if query_filter is not None else [point_a, point_b]
        return res

    mock_client = MagicMock()
    mock_client.search.side_effect = Exception("qdrant ≥1.11: API renovada")
    mock_client.query_points.side_effect = _smart_query_points

    QdrantAdapter = _load_qdrant_adapter()
    adapter = QdrantAdapter(client=mock_client)
    results = adapter.search_with_filter(
        collection_name="test-collection",
        query_vector=[0.1] * 4,
        filter_conditions=[{"key": "user_id", "value": "user-A"}],
    )

    user_ids_returned = [r.payload["user_id"] for r in results]
    assert "user-B" not in user_ids_returned, (
        "B2 privacy leak: query de user-A ha retornat dades de user-B "
        "(query_filter no aplicat al fallback query_points())"
    )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Anti-reg B2: el bloc except de search_with_filter no conté query_filter= "
        "— guard estructural per detectar eliminació silenciosa del fix. (Onada 4.6b, pre-fix)"
    ),
)
def test_qdrant_adapter_fallback_passes_filter():
    """Anti-regressió B2: el bloc except de search_with_filter conté query_filter=.

    Pin estàtic via lectura de font per detectar eliminació silenciosa del fix.
    Post-fix: 'query_filter' ha d'aparèixer al bloc except de search_with_filter.
    Dev#2 treu el xfail quan el fix és aplicat.
    """
    src = _ADAPTER_FILE.read_text()

    fn_start = src.find("def search_with_filter")
    next_def = src.find("\n    def ", fn_start + 1)
    fn_src = src[fn_start:next_def] if next_def > fn_start > 0 else src[fn_start:]

    except_idx = fn_src.find("except")
    fallback_src = fn_src[except_idx:] if except_idx >= 0 else ""

    assert "query_filter" in fallback_src, (
        "Anti-reg B2: el fallback query_points() ha de passar query_filter= "
        "— fix B2 absent o eliminat silenciosament"
    )
