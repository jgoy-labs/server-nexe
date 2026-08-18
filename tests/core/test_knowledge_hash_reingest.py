"""Knowledge auto-ingest must follow the docs, not the old doc_count gate.

knowledge/ARCHITECTURE.md and RAG.md (ca/en/es) say embeddings regenerate
when the .md files or the embedding model change. The previous marker was
an empty file plus ``doc_count >= 10`` — that skipped ingest forever after
the first successful run.

These tests use a REAL on-disk tree and the REAL hasher. Qdrant is faked
only at the API boundary. If someone restores the old ``>= 10`` skip, the
legacy-marker test dies.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from core.lifespan_modules import (
    _check_needs_reingest,
    _embedding_model_name,
    _write_ingest_marker,
    auto_ingest_knowledge,
    knowledge_source_fingerprint,
)


MODEL = "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"


def _kb_tree(tmp_path: Path, text: str = "hello nexe") -> Path:
    kb = tmp_path / "knowledge"
    kb.mkdir()
    (kb / "note.md").write_text(text, encoding="utf-8")
    return kb


class _FakeApi:
    def __init__(self, exists: bool = True, count: int = 99):
        self._exists = exists
        self._count = count

    async def collection_exists(self, name: str) -> bool:
        assert name == "nexe_documentation"
        return self._exists

    async def count(self, name: str) -> int:
        assert name == "nexe_documentation"
        return self._count


# ── fingerprint is real, not a stub ─────────────────────────────────────────


def test_fingerprint_changes_when_file_content_changes(tmp_path):
    kb = _kb_tree(tmp_path, "alpha")
    first = knowledge_source_fingerprint(kb, MODEL)
    (kb / "note.md").write_text("beta", encoding="utf-8")
    second = knowledge_source_fingerprint(kb, MODEL)
    assert first != second
    assert first.endswith(":" + MODEL)
    assert len(first.split(":")[0]) == 64


def test_fingerprint_stable_for_same_bytes(tmp_path):
    kb = _kb_tree(tmp_path, "same")
    a = knowledge_source_fingerprint(kb, MODEL)
    (kb / "note.md").write_text("same", encoding="utf-8")
    b = knowledge_source_fingerprint(kb, MODEL)
    assert a == b


def test_fingerprint_changes_when_model_changes(tmp_path):
    kb = _kb_tree(tmp_path)
    assert knowledge_source_fingerprint(kb, "model-a") != knowledge_source_fingerprint(
        kb, "model-b"
    )


# ── the old gate is dead ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_legacy_empty_marker_reingests_even_with_many_docs(tmp_path):
    """Empty marker + 99 docs used to SKIP. Docs say regenerate. Must ingest."""
    kb = _kb_tree(tmp_path)
    marker = tmp_path / "storage" / ".knowledge_ingested"
    marker.parent.mkdir()
    marker.write_text("", encoding="utf-8")

    with patch(
        "memory.memory.api.v1.get_memory_api",
        new=AsyncMock(return_value=_FakeApi(count=99)),
    ):
        needed = await _check_needs_reingest(marker, kb, MODEL)

    assert needed is True
    assert not marker.exists()


@pytest.mark.asyncio
async def test_hash_mismatch_reingests_even_when_count_is_high(tmp_path):
    kb = _kb_tree(tmp_path, "now")
    marker = tmp_path / "storage" / ".knowledge_ingested"
    marker.parent.mkdir()
    _write_ingest_marker(marker, "0" * 64 + ":" + MODEL)

    with patch(
        "memory.memory.api.v1.get_memory_api",
        new=AsyncMock(return_value=_FakeApi(count=99)),
    ):
        needed = await _check_needs_reingest(marker, kb, MODEL)

    assert needed is True


@pytest.mark.asyncio
async def test_matching_hash_skips(tmp_path):
    kb = _kb_tree(tmp_path)
    marker = tmp_path / "storage" / ".knowledge_ingested"
    marker.parent.mkdir()
    _write_ingest_marker(marker, knowledge_source_fingerprint(kb, MODEL))

    with patch(
        "memory.memory.api.v1.get_memory_api",
        new=AsyncMock(return_value=_FakeApi(count=99)),
    ):
        needed = await _check_needs_reingest(marker, kb, MODEL)

    assert needed is False
    assert marker.exists()


@pytest.mark.asyncio
async def test_matching_hash_but_missing_collection_reingests(tmp_path):
    kb = _kb_tree(tmp_path)
    marker = tmp_path / "storage" / ".knowledge_ingested"
    marker.parent.mkdir()
    _write_ingest_marker(marker, knowledge_source_fingerprint(kb, MODEL))

    with patch(
        "memory.memory.api.v1.get_memory_api",
        new=AsyncMock(return_value=_FakeApi(exists=False, count=0)),
    ):
        needed = await _check_needs_reingest(marker, kb, MODEL)

    assert needed is True


# ── auto_ingest writes the fingerprint and asks for a replace ───────────────


def _enable_ingest(monkeypatch):
    monkeypatch.setenv("NEXE_ENV", "development")
    monkeypatch.setenv("NEXE_AUTO_INGEST_KNOWLEDGE", "true")
    monkeypatch.delenv("NEXE_LANG", raising=False)


@pytest.mark.asyncio
async def test_auto_ingest_skips_when_fingerprint_matches(tmp_path, monkeypatch):
    _enable_ingest(monkeypatch)
    kb = _kb_tree(tmp_path)
    marker = tmp_path / "storage" / ".knowledge_ingested"
    marker.parent.mkdir()
    _write_ingest_marker(marker, knowledge_source_fingerprint(kb, _embedding_model_name()))

    ingest = AsyncMock(return_value=True)
    with (
        patch("core.sidecar_config.get_sidecar_config", side_effect=RuntimeError("no sidecar")),
        patch("core.ingest.ingest_knowledge.ingest_knowledge", ingest),
        patch(
            "memory.memory.api.v1.get_memory_api",
            new=AsyncMock(return_value=_FakeApi(count=12)),
        ),
    ):
        await auto_ingest_knowledge(SimpleNamespace(project_root=tmp_path))

    ingest.assert_not_called()


@pytest.mark.asyncio
async def test_auto_ingest_replaces_and_writes_fingerprint_on_change(
    tmp_path, monkeypatch
):
    _enable_ingest(monkeypatch)
    kb = _kb_tree(tmp_path, "before")
    marker = tmp_path / "storage" / ".knowledge_ingested"
    marker.parent.mkdir()
    _write_ingest_marker(marker, "deadbeef:" + MODEL)
    (kb / "note.md").write_text("after — docs changed", encoding="utf-8")

    ingest = AsyncMock(return_value=True)
    with (
        patch("core.sidecar_config.get_sidecar_config", side_effect=RuntimeError("no sidecar")),
        patch("core.ingest.ingest_knowledge.ingest_knowledge", ingest),
    ):
        await auto_ingest_knowledge(SimpleNamespace(project_root=tmp_path))

    ingest.assert_called_once()
    kwargs = ingest.call_args.kwargs
    assert kwargs["replace_existing"] is True
    assert kwargs["target_collection"] == "nexe_documentation"
    expected = knowledge_source_fingerprint(kb, _embedding_model_name())
    assert marker.read_text(encoding="utf-8").strip() == expected


@pytest.mark.asyncio
async def test_replace_collection_drops_then_recreates():
    """A re-ingest that only upserts would stack old chunk ids. Wipe first."""
    from core.ingest.ingest_knowledge import _replace_collection

    memory = SimpleNamespace(
        collection_exists=AsyncMock(return_value=True),
        delete_collection=AsyncMock(),
        create_collection=AsyncMock(),
    )
    logs: list[str] = []
    ok = await _replace_collection(memory, "nexe_documentation", logs.append)
    assert ok is True
    memory.delete_collection.assert_awaited_once_with("nexe_documentation")
    memory.create_collection.assert_awaited_once()
    assert memory.create_collection.await_args.args[0] == "nexe_documentation"
