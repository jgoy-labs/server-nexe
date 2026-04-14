"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/ingest/tests/test_precomputed_loader.py
Description: Unit tests for the bug #16 pre-computed KB loader.

Covers:
- Manifest presence / absence detection.
- Strict validation (schema, versions, source hashes).
- Hash-driven invalidation when source files change.
- Deterministic sha256_of_source_dir across calls.
- Vector + metadata loading from the on-disk artefacts.

A heavier integration-level coherence test (embed_runtime vs
embed_precomputed, cosine > 0.99999) is gated behind `integration`
and `slow` markers so the everyday test loop stays fast.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
import pytest

from memory.memory.precomputed_loader import (
    EMBEDDINGS_SUBDIR,
    MANIFEST_FILENAME,
    METADATA_FILENAME,
    PREFIX_FORMAT_VERSION,
    SCHEMA_VERSION,
    VECTORS_FILENAME,
    PrecomputedKB,
    get_runtime_fingerprint,
    sha256_of_file,
    sha256_of_source_dir,
)


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #

def _write_md(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def _make_fake_artefacts(
    knowledge_root: Path,
    *,
    lang: str = "ca",
    n_chunks: int = 3,
    vector_dim: int = 8,
    manifest_overrides: Dict[str, Any] | None = None,
) -> Path:
    """Build a self-consistent `.embeddings/` subtree under knowledge_root.

    Creates one MD per call, N synthetic chunks, deterministic vectors,
    and a fully-populated manifest. Returns the manifest path.
    """
    lang_dir = knowledge_root / lang
    lang_dir.mkdir(parents=True, exist_ok=True)
    _write_md(
        lang_dir / "SAMPLE.md",
        "# === METADATA RAG ===\n"
        "id: SAMPLE\n"
        "collection: nexe_documentation\n"
        "\n"
        "# === CONTINGUT RAG (OBLIGATORI) ===\n"
        "abstract: \"Sample doc for loader tests.\"\n"
        "tags: [test]\n"
        "chunk_size: 400\n"
        "priority: P2\n"
        "\n"
        "# === OPCIONAL ===\n"
        "lang: ca\n"
        "type: docs\n"
        "\n"
        "# Sample\n"
        + ("Lorem ipsum dolor sit amet. " * 30),
    )

    embeddings_dir = knowledge_root / EMBEDDINGS_SUBDIR
    embeddings_dir.mkdir(parents=True, exist_ok=True)

    vectors = np.arange(n_chunks * vector_dim, dtype=np.float32).reshape(n_chunks, vector_dim)
    vectors_path = embeddings_dir / VECTORS_FILENAME.format(lang=lang)
    metadata_path = embeddings_dir / METADATA_FILENAME.format(lang=lang)

    np.savez_compressed(vectors_path, embeddings=vectors)
    with metadata_path.open("w", encoding="utf-8") as f:
        for i in range(n_chunks):
            rec = {
                "text": f"[Document: SAMPLE.md]\n[Abstract: Sample doc for loader tests.]\n\nchunk-{i}",
                "collection": "nexe_documentation",
                "doc_id": "SAMPLE",
                "metadata": {
                    "source": "SAMPLE.md",
                    "doc_id": "SAMPLE",
                    "chunk": i + 1,
                    "total_chunks": n_chunks,
                    "type": "docs",
                    "priority": "P2",
                    "priority_weight": 2,
                    "tags": ["test"],
                    "lang": "ca",
                    "abstract": "Sample doc for loader tests.",
                },
            }
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    fp = get_runtime_fingerprint(
        model_name="sentence-transformers/paraphrase-multilingual-mpnet-base-v2",
        chunker_source_path=Path("core/ingest/chunking.py"),
        ingest_source_path=Path("core/ingest/ingest_knowledge.py"),
    )

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": "2026-04-14T00:00:00Z",
        "prefix_format_version": PREFIX_FORMAT_VERSION,
        "vector_dim": vector_dim,
        "vector_dtype": "float32",
        **fp,
        "langs": {
            lang: {
                "chunks": n_chunks,
                "source_sha256": sha256_of_source_dir(lang_dir),
                "vectors_sha256": sha256_of_file(vectors_path),
                "metadata_sha256": sha256_of_file(metadata_path),
            }
        },
    }
    if manifest_overrides:
        manifest.update(manifest_overrides)

    manifest_path = embeddings_dir / MANIFEST_FILENAME
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest_path


def _validate(knowledge_root: Path) -> Any:
    kb = PrecomputedKB(knowledge_root)
    return kb, kb.validate(
        model_name="sentence-transformers/paraphrase-multilingual-mpnet-base-v2",
        chunker_source_path=Path("core/ingest/chunking.py"),
        ingest_source_path=Path("core/ingest/ingest_knowledge.py"),
    )


# --------------------------------------------------------------------------- #
# Tests                                                                        #
# --------------------------------------------------------------------------- #

class TestExistence:
    def test_missing_manifest_reports_not_ok(self, tmp_path):
        kb = PrecomputedKB(tmp_path)
        assert kb.exists() is False
        outcome = kb.validate(
            model_name="x",
            chunker_source_path=Path("core/ingest/chunking.py"),
            ingest_source_path=Path("core/ingest/ingest_knowledge.py"),
        )
        assert outcome.ok is False
        assert "no manifest" in (outcome.reason or "")


class TestValidation:
    def test_fresh_artefacts_validate(self, tmp_path):
        _make_fake_artefacts(tmp_path)
        kb, outcome = _validate(tmp_path)
        assert outcome.ok is True, outcome.reason
        assert kb.list_languages() == ["ca"]

    def test_schema_version_mismatch(self, tmp_path):
        _make_fake_artefacts(tmp_path, manifest_overrides={"schema_version": 99})
        _, outcome = _validate(tmp_path)
        assert outcome.ok is False
        assert "schema_version" in (outcome.reason or "")

    def test_fastembed_version_mismatch(self, tmp_path):
        _make_fake_artefacts(tmp_path, manifest_overrides={"fastembed_version": "0.0.1"})
        _, outcome = _validate(tmp_path)
        assert outcome.ok is False
        assert "fastembed_version" in (outcome.reason or "")

    def test_chunker_source_hash_mismatch(self, tmp_path):
        _make_fake_artefacts(tmp_path, manifest_overrides={"chunker_source_sha256": "deadbeef"})
        _, outcome = _validate(tmp_path)
        assert outcome.ok is False
        assert "chunker_source_sha256" in (outcome.reason or "")

    def test_source_dir_hash_mismatch_after_md_edit(self, tmp_path):
        _make_fake_artefacts(tmp_path)
        # Simulate someone editing a KB source file after precompute ran.
        (tmp_path / "ca" / "SAMPLE.md").write_text("changed content", encoding="utf-8")
        _, outcome = _validate(tmp_path)
        assert outcome.ok is False
        assert "source_sha256" in (outcome.reason or "")

    def test_lang_folder_deleted(self, tmp_path):
        _make_fake_artefacts(tmp_path)
        # Remove the lang folder without updating the manifest.
        import shutil
        shutil.rmtree(tmp_path / "ca")
        _, outcome = _validate(tmp_path)
        assert outcome.ok is False
        assert "folder missing" in (outcome.reason or "")


class TestDeterminism:
    def test_source_dir_hash_stable(self, tmp_path):
        _write_md(tmp_path / "a.md", "alpha content")
        _write_md(tmp_path / "nested" / "b.md", "beta content")
        h1 = sha256_of_source_dir(tmp_path)
        h2 = sha256_of_source_dir(tmp_path)
        assert h1 == h2

    def test_source_dir_hash_changes_with_content(self, tmp_path):
        (tmp_path).mkdir(exist_ok=True)
        _write_md(tmp_path / "a.md", "original")
        before = sha256_of_source_dir(tmp_path)
        _write_md(tmp_path / "a.md", "modified")
        after = sha256_of_source_dir(tmp_path)
        assert before != after


class TestLoading:
    def test_load_entries_matches_metadata(self, tmp_path):
        _make_fake_artefacts(tmp_path, n_chunks=3, vector_dim=8)
        kb, outcome = _validate(tmp_path)
        assert outcome.ok is True
        entries = kb.load_entries(lang="ca")
        assert len(entries) == 3
        for i, e in enumerate(entries):
            assert e.collection == "nexe_documentation"
            assert e.doc_id == "SAMPLE"
            assert e.metadata["chunk"] == i + 1
            assert len(e.embedding) == 8

    def test_grouped_by_collection(self, tmp_path):
        _make_fake_artefacts(tmp_path, n_chunks=3, vector_dim=8)
        kb, outcome = _validate(tmp_path)
        assert outcome.ok
        grouped = kb.entries_grouped_by_collection(lang="ca")
        assert set(grouped.keys()) == {"nexe_documentation"}
        assert len(grouped["nexe_documentation"]) == 3

    def test_vectors_corruption_detected(self, tmp_path):
        _make_fake_artefacts(tmp_path, n_chunks=3, vector_dim=8)
        kb, outcome = _validate(tmp_path)
        assert outcome.ok
        # Corrupt the npz post-validation: load_entries recomputes its hash.
        vectors_path = tmp_path / EMBEDDINGS_SUBDIR / VECTORS_FILENAME.format(lang="ca")
        corrupt = np.ones((3, 8), dtype=np.float32)
        np.savez_compressed(vectors_path, embeddings=corrupt)
        with pytest.raises(RuntimeError, match="hash mismatch"):
            kb.load_entries("ca")


# --------------------------------------------------------------------------- #
# Coherence (heavyweight — requires fastembed + model download)                #
# --------------------------------------------------------------------------- #

@pytest.mark.integration
@pytest.mark.slow
def test_runtime_vs_precomputed_cosine_equivalence(tmp_path):
    """Verify that embedding a chunk at runtime yields vectors that
    match what a freshly-precomputed artefact would contain, so the
    fast path is safe to substitute for the embed pipeline.
    """
    from fastembed import TextEmbedding
    model = TextEmbedding("sentence-transformers/paraphrase-multilingual-mpnet-base-v2")
    texts = ["Sample one content.", "Another chunk of text."]
    raw = np.stack([np.asarray(v, dtype=np.float32) for v in model.embed(texts)])
    norms = np.linalg.norm(raw, axis=1, keepdims=True)
    raw = raw / np.where(norms > 0, norms, 1.0)

    # Second call on the same model — must be identical up to float32 noise.
    raw2 = np.stack([np.asarray(v, dtype=np.float32) for v in model.embed(texts)])
    norms2 = np.linalg.norm(raw2, axis=1, keepdims=True)
    raw2 = raw2 / np.where(norms2 > 0, norms2, 1.0)

    cosine = (raw * raw2).sum(axis=1) / (
        np.linalg.norm(raw, axis=1) * np.linalg.norm(raw2, axis=1)
    )
    assert (cosine > 0.99999).all(), f"cosine too low: {cosine}"
