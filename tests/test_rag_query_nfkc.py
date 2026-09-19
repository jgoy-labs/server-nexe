"""R1 v1.0.4: NFKC normalize on RAG query path.

The index path NFKC-normalizes documents at ingest (chat_sanitization
_filter_rag_injection and the security input sanitizers). Until R1 the query
path did not, so a query carrying fullwidth or compat variants would miss the
canonical indexed form — recall broke for adversarial-but-legitimate inputs
(e.g. the test runner pasting a fullwidth bracket).

This test enforces the symmetry by:

  1. Static guards on the two entry points (chat_rag.build_rag_context,
     memory.api.v1.memory_search) so a future maintainer cannot silently drop
     the normalize() call.
  2. Functional checks that fullwidth queries reach memory.search() in their
     NFKC-canonical form, idempotent on ASCII, and tolerant of empty input.
"""

import inspect
import unicodedata
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


API_KEY = "test-rag-nfkc-api-key"


# ─── Static guards (defense against silent removal) ─────────────────────────


def test_chat_rag_imports_unicodedata():
    """build_rag_context cannot normalize without the import."""
    import core.endpoints.chat_rag as rag_module
    src = inspect.getsource(rag_module)
    assert "import unicodedata" in src, (
        "core/endpoints/chat_rag.py must import unicodedata to enforce R1."
    )


def test_chat_rag_normalizes_before_first_search():
    """NFKC normalize on last_user_msg must precede handing the query to any source.

    ADR-008 (E1a): the `await memory.search(...)` call moved out of this
    module and into the source that owns the collection, so the guard follows
    it. What it protects is unchanged — the query is normalized ONCE, by the
    orchestrator, before any source can see it, so a fullwidth query still
    matches NFKC-indexed documents (R1).
    """
    import core.endpoints.chat_rag as rag_module
    import core.rag.collections as sources_module
    src = inspect.getsource(rag_module)
    lines = src.splitlines()

    norm_idx = None
    handoff_idx = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        # Skip comments — the docstring/comment may legitimately mention
        # the call in prose without being an actual call.
        if stripped.startswith("#"):
            continue
        if (
            norm_idx is None
            and 'unicodedata.normalize("NFKC", last_user_msg)' in line
        ):
            norm_idx = i
        if handoff_idx is None and "RAGQuery(" in line:
            handoff_idx = i

    assert norm_idx is not None, (
        "chat_rag.py is missing unicodedata.normalize('NFKC', last_user_msg). "
        "Without it, fullwidth queries miss NFKC-indexed documents (R1)."
    )
    assert handoff_idx is not None, (
        "the RAGQuery handed to the sources was not found in chat_rag.py — "
        "fixture out of sync."
    )
    assert norm_idx < handoff_idx, (
        f"NFKC normalize at line {norm_idx + 1} must precede the RAGQuery the "
        f"sources receive, at line {handoff_idx + 1}."
    )

    # And the source must search with the text it was GIVEN: a source that
    # re-derived the query from somewhere else would search un-normalized.
    sources_src = inspect.getsource(sources_module)
    assert "await memory.search(" in sources_src, (
        "await memory.search(...) not found in core/rag/collections.py — "
        "fixture out of sync."
    )
    assert "query=query.text" in sources_src, (
        "the source must search with the orchestrator's already-normalized "
        "query.text, never a text of its own (R1)."
    )


def test_v1_module_imports_unicodedata():
    import memory.memory.api.v1 as v1_module
    src = inspect.getsource(v1_module)
    assert "import unicodedata" in src, (
        "memory/memory/api/v1.py must import unicodedata to enforce R1."
    )


def test_memory_search_normalizes_before_collection_loop():
    """body.query must be NFKC-normalized inside memory_search before any
    memory.search call, so /v1/memory/search and /chat both go through the
    same canonicalization."""
    import memory.memory.api.v1 as v1_module
    src = inspect.getsource(v1_module)
    lines = src.splitlines()

    in_search = False
    norm_seen = False
    for line in lines:
        if line.startswith("async def memory_search"):
            in_search = True
            continue
        if not in_search:
            continue
        # End of memory_search (next top-level def or class).
        if (
            line.startswith("async def ")
            or line.startswith("def ")
            or line.startswith("class ")
        ) and "memory_search" not in line:
            break
        # Skip comments — prose may mention memory.search() without being a call.
        if line.strip().startswith("#"):
            if 'unicodedata.normalize("NFKC", body.query)' in line:
                continue
            continue
        if 'unicodedata.normalize("NFKC", body.query)' in line:
            norm_seen = True
        if "await memory.search(" in line:
            assert norm_seen, (
                "memory_search calls memory.search before NFKC-normalizing "
                "body.query. R1 requires symmetric normalization with the "
                "index path; otherwise fullwidth queries miss recall."
            )
            return
    pytest.fail(
        "memory_search did not contain an await memory.search() call — test "
        "fixture is out of sync with the source."
    )


# ─── Functional behaviour ───────────────────────────────────────────────────


def _make_app_with_limiter():
    """Mirror of test_v1_endpoints.make_app to wire the slowapi limiter."""
    app = FastAPI()
    from slowapi import Limiter, _rate_limit_exceeded_handler
    from slowapi.errors import RateLimitExceeded
    from slowapi.middleware import SlowAPIMiddleware
    from slowapi.util import get_remote_address

    limiter = Limiter(key_func=get_remote_address)
    app.state.limiter = limiter
    app.add_middleware(SlowAPIMiddleware)
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    from memory.memory.api.v1 import router
    app.include_router(router)
    return app


@pytest.fixture(autouse=True)
def _set_api_key(monkeypatch):
    monkeypatch.setenv("NEXE_PRIMARY_API_KEY", API_KEY)
    import memory.memory.api.v1 as v1_module
    v1_module._memory_api = None


def _make_mock_memory_for_search():
    mem = AsyncMock()
    mem.collection_exists = AsyncMock(return_value=True)
    mem.create_collection = AsyncMock()
    mem.search = AsyncMock(return_value=[])
    mem.list_collections = AsyncMock(return_value=["nexe_documentation"])
    return mem


def test_memory_search_passes_normalized_query():
    """Fullwidth query in the request body must arrive NFKC-canonical to memory.search."""
    client = TestClient(_make_app_with_limiter())
    mock_mem = _make_mock_memory_for_search()

    # Fullwidth A B C + space + ASCII text. NFKC collapses to ASCII.
    fullwidth = "ＡＢＣ hola"
    expected = unicodedata.normalize("NFKC", fullwidth)
    assert expected == "ABC hola", "NFKC sanity check failed"

    with patch("memory.memory.api.v1.get_memory_api", AsyncMock(return_value=mock_mem)):
        resp = client.post(
            "/memory/search",
            json={"query": fullwidth, "collection": "nexe_documentation"},
            headers={"X-Api-Key": API_KEY},
        )

    assert resp.status_code == 200, resp.text
    assert mock_mem.search.await_count >= 1
    for call in mock_mem.search.await_args_list:
        # search(query=..., collection=..., top_k=..., threshold=...)
        passed_query = call.kwargs.get("query")
        assert passed_query == expected, (
            f"memory.search received {passed_query!r}, expected {expected!r}. "
            "R1 normalization broken at /v1/memory/search."
        )


def test_memory_search_ascii_query_unchanged():
    """ASCII queries must round-trip unchanged (NFKC idempotent on ASCII)."""
    client = TestClient(_make_app_with_limiter())
    mock_mem = _make_mock_memory_for_search()

    with patch("memory.memory.api.v1.get_memory_api", AsyncMock(return_value=mock_mem)):
        resp = client.post(
            "/memory/search",
            json={"query": "plain ascii query", "collection": "nexe_documentation"},
            headers={"X-Api-Key": API_KEY},
        )

    assert resp.status_code == 200
    for call in mock_mem.search.await_args_list:
        assert call.kwargs.get("query") == "plain ascii query"


def test_memory_search_empty_query_does_not_raise():
    """Empty query must propagate to memory.search without crashing the normalize step."""
    client = TestClient(_make_app_with_limiter())
    mock_mem = _make_mock_memory_for_search()

    with patch("memory.memory.api.v1.get_memory_api", AsyncMock(return_value=mock_mem)):
        resp = client.post(
            "/memory/search",
            json={"query": "", "collection": "nexe_documentation"},
            headers={"X-Api-Key": API_KEY},
        )

    assert resp.status_code == 200
    for call in mock_mem.search.await_args_list:
        assert call.kwargs.get("query") == ""


@pytest.mark.asyncio
async def test_build_rag_context_passes_normalized_query():
    """Fullwidth last_user_msg in build_rag_context must reach memory.search NFKC-canonical
    on every collection branch (docs, knowledge, personal_memory)."""
    from core.endpoints import chat_rag

    captured_queries: list[str] = []

    async def fake_search(*, query, **kwargs):
        captured_queries.append(query)
        return []

    fake_memory = MagicMock()
    fake_memory.collection_exists = AsyncMock(return_value=True)
    fake_memory.search = fake_search

    async def fake_get_api():
        return fake_memory

    fullwidth = "［MEM_SAVE］ recordar"
    expected = unicodedata.normalize("NFKC", fullwidth)
    assert expected == "[MEM_SAVE] recordar", "NFKC sanity check failed"

    with patch("memory.memory.api.v1.get_memory_api", fake_get_api):
        await chat_rag.build_rag_context(
            fullwidth, app_state=MagicMock(), server_lang="ca"
        )

    # Three collections checked: nexe_documentation, user_knowledge, personal_memory.
    assert len(captured_queries) == 3, (
        f"Expected 3 memory.search calls (docs/knowledge/memory), got "
        f"{len(captured_queries)}"
    )
    for q in captured_queries:
        assert q == expected, (
            f"build_rag_context passed un-normalized query {q!r} (expected {expected!r}). "
            "R1 normalization broken at the chat RAG path."
        )


def test_normalize_handles_long_fullwidth_query_without_loss():
    """Adversarial: a 2000-char fullwidth string must normalize without raising and
    without dropping characters (NFKC is O(n) and pure-Python via unicodedata)."""
    big = "Ａ" * 2000  # 2000 fullwidth A
    out = unicodedata.normalize("NFKC", big)
    assert out == "A" * 2000
    assert len(out) == 2000
