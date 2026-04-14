"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/ingest/tests/test_ingest_knowledge_mega_batch.py
Description: Parity tests for bug #16 mega_batch flag.

Verifies that the mega-batch code path in `ingest_knowledge` produces
the same items (identical text + metadata) as the legacy per-file path.
The only observable difference between the two paths should be the
number of `store_batch` invocations: legacy emits one per file, mega
emits one per destination collection.

These tests use an in-process MemoryAPI double that captures every item
handed to `store_batch` / `store` without requiring Qdrant or fastembed,
so they are fast and deterministic.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from memory.memory.config import IngestConfig


def _build_capturing_memory() -> tuple[MagicMock, List[Dict[str, Any]]]:
    """Return (mock_memory, captured_items) where every stored item is
    appended to `captured_items` with its destination collection."""
    captured: List[Dict[str, Any]] = []
    mock = MagicMock()
    mock.initialize = AsyncMock()
    mock.collection_exists = AsyncMock(return_value=True)
    mock.create_collection = AsyncMock()
    mock.close = AsyncMock()

    async def _store_batch(items, collection):
        for it in items:
            captured.append({
                "text": it["text"],
                "metadata": dict(it["metadata"]),
                "collection": collection,
            })
        return ["id"] * len(items)

    async def _store(text, collection, metadata):
        captured.append({
            "text": text,
            "metadata": dict(metadata),
            "collection": collection,
        })
        return "id"

    mock.store_batch = AsyncMock(side_effect=_store_batch)
    mock.store = AsyncMock(side_effect=_store)
    return mock, captured


def _write_multi_file_corpus(root: Path) -> Path:
    """Stage a handful of .md files with RAG headers to exercise the
    code paths that extract metadata (doc_id, priority, tags, lang)."""
    knowledge = root / "knowledge"
    knowledge.mkdir()

    (knowledge / "ALPHA.md").write_text(
        "# === METADATA RAG ===\n"
        "versio: \"1.0\"\n"
        "id: ALPHA\n"
        "collection: nexe_documentation\n"
        "\n"
        "# === CONTINGUT RAG (OBLIGATORI) ===\n"
        "abstract: \"Alpha test document for parity checks.\"\n"
        "tags: [alpha, test]\n"
        "chunk_size: 600\n"
        "priority: P1\n"
        "\n"
        "# === OPCIONAL ===\n"
        "lang: ca\n"
        "type: docs\n"
        "\n"
        "# Alpha\n\n"
        "Aquest és el contingut del document alpha. "
        "Té prou text per generar un chunk raonable dins el pipeline. "
        + ("Contingut addicional per assegurar múltiples chunks. " * 40)
    )
    (knowledge / "BETA.md").write_text(
        "# === METADATA RAG ===\n"
        "versio: \"1.0\"\n"
        "id: BETA\n"
        "collection: nexe_documentation\n"
        "\n"
        "# === CONTINGUT RAG (OBLIGATORI) ===\n"
        "abstract: \"Beta test doc.\"\n"
        "tags: [beta]\n"
        "chunk_size: 400\n"
        "priority: P2\n"
        "\n"
        "# === OPCIONAL ===\n"
        "lang: ca\n"
        "type: api\n"
        "\n"
        "# Beta\n\n"
        + ("Text beta per generar chunks amb overlap. " * 25)
    )
    (knowledge / "GAMMA.txt").write_text(
        "This file has no RAG header and should fall through to defaults. "
        + ("More text " * 30)
    )
    return knowledge


def _normalize_items_for_comparison(items: List[Dict[str, Any]]) -> List[tuple]:
    """Items are keyed by (collection, text). Metadata is compared as a
    sorted tuple of (key, value) pairs so dict ordering does not matter.
    Returns a sorted list of tuples so set-equality checks work reliably
    regardless of arrival order (mega flushes per collection, legacy
    flushes per file — the order of individual items within those
    batches is otherwise identical)."""
    out = []
    for it in items:
        meta_pairs = tuple(sorted(
            (k, tuple(v) if isinstance(v, list) else v)
            for k, v in it["metadata"].items()
        ))
        out.append((it["collection"], it["text"], meta_pairs))
    return sorted(out)


@pytest.fixture
def corpus(tmp_path):
    _write_multi_file_corpus(tmp_path)
    return tmp_path


def _run_with_config(corpus_root: Path, ingest_cfg: IngestConfig) -> tuple[MagicMock, List[Dict[str, Any]]]:
    """Execute the ingest pipeline once with the given IngestConfig and
    return the captured items. Monkey-patches MemoryAPI to force the
    mock and injects our config via the MemoryAPI constructor hook."""
    from core.ingest.ingest_knowledge import ingest_knowledge

    mock_memory, captured = _build_capturing_memory()
    mock_memory.ingest_config = ingest_cfg

    with patch("memory.memory.api.MemoryAPI", return_value=mock_memory), \
         patch("core.ingest.ingest_knowledge.PROJECT_ROOT", corpus_root):
        result = asyncio.run(ingest_knowledge())
    assert result is True, "ingest_knowledge returned False"
    return mock_memory, captured


class TestMegaBatchParity:
    """Bug #16: mega_batch=True must yield the same items as the legacy
    per-file path, with identical metadata and destination collections."""

    def test_items_are_identical(self, corpus):
        _, legacy_items = _run_with_config(corpus, IngestConfig(mega_batch=False))
        _, mega_items = _run_with_config(corpus, IngestConfig(mega_batch=True))

        assert len(legacy_items) == len(mega_items), (
            f"Item count differs: legacy={len(legacy_items)} mega={len(mega_items)}"
        )
        legacy_norm = _normalize_items_for_comparison(legacy_items)
        mega_norm = _normalize_items_for_comparison(mega_items)
        assert legacy_norm == mega_norm, (
            "Mega-batch path produces different items than legacy path"
        )

    def test_mega_uses_fewer_store_batch_calls(self, corpus):
        legacy_mock, _ = _run_with_config(corpus, IngestConfig(mega_batch=False))
        mega_mock, _ = _run_with_config(corpus, IngestConfig(mega_batch=True))

        # The legacy path invokes store_batch once per file (3 files);
        # mega should invoke it once per destination collection. Our
        # corpus has a single collection (`nexe_documentation`), so mega
        # must call exactly once.
        assert legacy_mock.store_batch.call_count >= 3, (
            f"Legacy expected ≥3 store_batch calls, got {legacy_mock.store_batch.call_count}"
        )
        assert mega_mock.store_batch.call_count == 1, (
            f"Mega expected exactly 1 store_batch call, got {mega_mock.store_batch.call_count}"
        )

    def test_collections_are_preserved(self, corpus):
        _, legacy_items = _run_with_config(corpus, IngestConfig(mega_batch=False))
        _, mega_items = _run_with_config(corpus, IngestConfig(mega_batch=True))

        legacy_colls = sorted({it["collection"] for it in legacy_items})
        mega_colls = sorted({it["collection"] for it in mega_items})
        assert legacy_colls == mega_colls

    def test_rag_metadata_preserved(self, corpus):
        """Spot-check that per-item RAG metadata survives in mega mode
        (doc_id, priority, lang, tags, source)."""
        _, mega_items = _run_with_config(corpus, IngestConfig(mega_batch=True))

        by_source = {it["metadata"]["source"]: it for it in mega_items}
        assert "ALPHA.md" in by_source
        assert "BETA.md" in by_source
        alpha_meta = by_source["ALPHA.md"]["metadata"]
        assert alpha_meta["doc_id"] == "ALPHA"
        assert alpha_meta["priority"] == "P1"
        assert alpha_meta["lang"] == "ca"
        assert "alpha" in alpha_meta["tags"]
        beta_meta = by_source["BETA.md"]["metadata"]
        assert beta_meta["doc_id"] == "BETA"
        assert beta_meta["priority"] == "P2"
        assert beta_meta["type"] == "api"
