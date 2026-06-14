"""
────────────────────────────────────
Server Nexe
Location: tests/test_installer_sha256_catalog.py
Description: Smoke tests for the MODEL_WEIGHT_SHA256 map and its helpers
             introduced by the SHA256 weight pinning (internal security review AUD-INT-001 §2.7). Enforces that:

             1. Every downloadable artefact referenced by MODEL_CATALOG has
                a matching entry in MODEL_WEIGHT_SHA256 (value may be None).
             2. Pinned hashes are syntactically valid SHA256 digests.
             3. get_expected_sha256() is case-sensitive about the engine
                label but forgiving of absent ids.
             4. Engine set is the canonical three.
────────────────────────────────────
"""

from __future__ import annotations

import re

import pytest

from installer.installer_catalog_data import (
    MODEL_CATALOG,
    MODEL_WEIGHT_SHA256,
    VALID_SHA256_ENGINES,
    get_expected_sha256,
    iter_catalog_model_ids,
)


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


# ════════════════════════════════════════════════════════════════════════
# Coverage between MODEL_CATALOG and MODEL_WEIGHT_SHA256
# ════════════════════════════════════════════════════════════════════════


def test_every_catalog_artifact_has_integrity_entry() -> None:
    missing: list[tuple[str, str]] = []
    for pair in iter_catalog_model_ids():
        if pair not in MODEL_WEIGHT_SHA256:
            missing.append(pair)
    assert not missing, (
        "MODEL_CATALOG references artefacts absent from MODEL_WEIGHT_SHA256 "
        "(new model added without a SHA256 entry — even as None):\n"
        + "\n".join(f"  {engine}: {mid}" for engine, mid in missing)
    )


def test_no_orphan_entries_in_integrity_map() -> None:
    """The reverse direction: any pinned entry must correspond to a real
    catalog artefact. Prevents stale pins surviving after a model is
    removed from the catalog — stale pins are invisible defense that
    rot."""
    live_pairs = set(iter_catalog_model_ids())
    orphans = sorted(
        pair for pair in MODEL_WEIGHT_SHA256 if pair not in live_pairs
    )
    assert not orphans, (
        "MODEL_WEIGHT_SHA256 has entries not referenced by MODEL_CATALOG:\n"
        + "\n".join(f"  {engine}: {mid}" for engine, mid in orphans)
    )


def test_nomic_embed_has_integrity_entry() -> None:
    # B146: the always-downloaded embeddings model must be in the integrity map
    # AND surfaced by the iterator (so coverage/orphan checks enforce it).
    assert ("ollama", "nomic-embed-text") in MODEL_WEIGHT_SHA256
    assert ("ollama", "nomic-embed-text") in set(iter_catalog_model_ids())


def test_ollama_pull_embeddings_verifies_integrity(monkeypatch) -> None:
    # B146: after a successful pull of nomic-embed-text the installer must run the
    # SHA256 integrity check on it (it was previously pulled completely unverified).
    from installer import installer_setup_models as sm

    class _Proc:
        def wait(self):
            return 0

    monkeypatch.setattr(sm.subprocess, "Popen", lambda *a, **k: _Proc())
    monkeypatch.setattr(sm, "t", lambda key, **kw: key)
    calls: list[tuple[str, str]] = []

    def _spy(engine, model_id, target, **kwargs):
        calls.append((engine, model_id))
        return True

    monkeypatch.setattr(sm, "verify_download_integrity", _spy)
    sm._ollama_pull_embeddings("ollama")

    assert ("ollama", "nomic-embed-text") in calls  # fail-before: never called


# ════════════════════════════════════════════════════════════════════════
# Format of pinned hashes
# ════════════════════════════════════════════════════════════════════════


def test_pinned_hashes_are_valid_sha256() -> None:
    bad: list[tuple[tuple[str, str], str]] = []
    for pair, digest in MODEL_WEIGHT_SHA256.items():
        if digest is None:
            continue
        if not _SHA256_RE.match(digest):
            bad.append((pair, digest))
    assert not bad, (
        "Pinned hashes must be 64 lowercase hex chars:\n"
        + "\n".join(f"  {pair}: {digest!r}" for pair, digest in bad)
    )


# ════════════════════════════════════════════════════════════════════════
# get_expected_sha256
# ════════════════════════════════════════════════════════════════════════


def test_get_expected_sha256_known_mlx_returns_none_legacy() -> None:
    # Freshly added catalog, every pin is None — legacy mode for now.
    assert get_expected_sha256("mlx", "mlx-community/gemma-3-4b-it-4bit") is None


def test_get_expected_sha256_unknown_id_returns_none() -> None:
    assert (
        get_expected_sha256("ollama", "some-user/experimental-tag:latest")
        is None
    )


def test_get_expected_sha256_rejects_unknown_engine() -> None:
    with pytest.raises(ValueError):
        get_expected_sha256("mlx-vlm", "whatever")  # type: ignore[arg-type]


def test_valid_engines_set_is_canonical() -> None:
    assert VALID_SHA256_ENGINES == frozenset({"mlx", "ollama", "gguf"})


def test_iter_catalog_model_ids_covers_three_backends() -> None:
    """The helper should enumerate every non-empty mlx/ollama/gguf entry.
    If this test fails, iter_catalog_model_ids() has silently skipped a
    backend or MODEL_CATALOG has grown a new field without an update."""
    seen_engines = {engine for engine, _ in iter_catalog_model_ids()}
    # At least MLX + Ollama are always present in the current catalog.
    # GGUF too, via Salamandra / DeepSeek / ALIA / Gemma 27B.
    assert {"mlx", "ollama", "gguf"}.issubset(seen_engines)


def test_catalog_iteration_count_nonzero() -> None:
    pairs = iter_catalog_model_ids()
    assert len(pairs) >= 14, (
        f"Expected at least 14 (mlx+ollama+gguf) artefacts; got {len(pairs)}"
    )


# ════════════════════════════════════════════════════════════════════════
# Sanity — catalog hasn't lost models
# ════════════════════════════════════════════════════════════════════════


def test_model_catalog_has_four_tiers() -> None:
    assert set(MODEL_CATALOG.keys()) == {"small", "medium", "large", "xlarge"}


def test_model_catalog_total_model_count() -> None:
    total = sum(len(ms) for ms in MODEL_CATALOG.values())
    # 2026-05-23 slim: catalog intentionally pruned for the public release
    # (small=1, medium=4, large=3, xlarge=7 = 15). Lower bound prevents
    # accidental erasure, not future additions.
    assert total >= 14, f"Catalog shrunk below 14 models: got {total}"
