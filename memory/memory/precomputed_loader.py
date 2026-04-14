"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: memory/memory/precomputed_loader.py
Description: Validate and load pre-computed KB embeddings (bug #16).

For a static knowledge base, embedding at install time is wasted work:
the vectors are deterministic given (model, chunker, prefix, source
files). This module loads pre-computed vectors generated offline by
`scripts/precompute_kb.py`, validates them against the current
environment via a hash manifest, and returns items ready for direct
upsert into Qdrant.

If any hash check fails (source file edited, chunker changed, model
bumped, etc.) the loader returns None and the caller falls back to
runtime embedding. This keeps the optimisation fail-safe.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# Versioned so we can evolve the manifest format without breaking old
# on-disk artefacts silently. Bump when any breaking change is made.
SCHEMA_VERSION = 1

# Stable identifier for the prefix template used in ingest_knowledge.py.
# Bump whenever the template string in ingest_knowledge.py changes so old
# pre-computed vectors are invalidated automatically.
PREFIX_FORMAT_VERSION = "1.0"

# The embeddings subtree relative to the `knowledge/` root.
EMBEDDINGS_SUBDIR = ".embeddings"
MANIFEST_FILENAME = "manifest.json"
VECTORS_FILENAME = "vectors-{lang}.npz"
METADATA_FILENAME = "metadata-{lang}.jsonl"


# --------------------------------------------------------------------------- #
# Fingerprinting helpers                                                       #
# --------------------------------------------------------------------------- #

def sha256_of_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_of_source_dir(lang_dir: Path) -> str:
    """Hash the sorted list of (relative_path, content) pairs for a lang dir.

    Deterministic across machines: same inputs → same hash. Ignores OS
    metadata (mtime, permissions).
    """
    h = hashlib.sha256()
    entries = sorted(p for p in lang_dir.rglob("*") if p.is_file() and not p.name.startswith("."))
    for p in entries:
        rel = p.relative_to(lang_dir).as_posix()
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        h.update(p.read_bytes())
        h.update(b"\0")
    return h.hexdigest()


def read_hf_model_commit(model_name: str) -> Optional[str]:
    """Best-effort: read the HF hub cache `refs/main` to identify the model
    revision. Returns None if the cache layout is not as expected (the
    caller should handle this by treating it as an unknown fingerprint).
    """
    hub = Path.home() / ".cache" / "huggingface" / "hub"
    folder = "models--" + model_name.replace("/", "--")
    refs = hub / folder / "refs" / "main"
    if not refs.is_file():
        return None
    return refs.read_text().strip()


def get_runtime_fingerprint(
    *,
    model_name: str,
    chunker_source_path: Path,
    ingest_source_path: Optional[Path] = None,  # kept for backwards compat; ignored
    prefix_format_version: str = PREFIX_FORMAT_VERSION,
) -> Dict[str, Any]:
    """Collect every value that, if changed, would invalidate pre-computed
    vectors. Returned as a plain dict so it can be embedded into the
    manifest or compared against one.

    Notes:
    - `ingest_source_path` used to be hashed here but it turned out to be
      too fragile: the ingest_knowledge.py file changes for many reasons
      unrelated to what text is embedded (log strings, helpers, RAG
      fast-path wiring, etc). The prefix contract lives in
      `prefix_format_version` — bump it whenever the prefix template
      changes semantically, and the manifest will invalidate. The chunker
      source hash still covers chunk boundary changes. Source MD edits
      are covered by the per-lang source_sha256. Together these suffice.
    - The argument is kept for call-site backwards compatibility.
    """
    _ = ingest_source_path  # explicitly unused; see docstring
    try:
        import fastembed  # type: ignore
        fastembed_version = getattr(fastembed, "__version__", "unknown")
    except Exception:
        fastembed_version = "unknown"
    try:
        import onnxruntime  # type: ignore
        ort_version = getattr(onnxruntime, "__version__", "unknown")
    except Exception:
        ort_version = "unknown"

    return {
        "fastembed_version": fastembed_version,
        "onnxruntime_version": ort_version,
        "model_name": model_name,
        "model_hf_commit": read_hf_model_commit(model_name),
        "chunker_source_sha256": sha256_of_file(chunker_source_path)
            if chunker_source_path.is_file() else None,
        "prefix_format_version": prefix_format_version,
    }


# --------------------------------------------------------------------------- #
# Data classes                                                                 #
# --------------------------------------------------------------------------- #

@dataclass
class PrecomputedEntry:
    """One chunk worth of pre-computed data ready for Qdrant upsert."""

    text: str
    metadata: Dict[str, Any]
    embedding: List[float]
    collection: str
    doc_id: Optional[str] = None


@dataclass
class ValidationOutcome:
    """Result of validate_manifest. Carries everything the caller needs
    to log a clear reason when invalidation happens."""

    ok: bool
    reason: Optional[str] = None
    manifest: Optional[Dict[str, Any]] = None


# --------------------------------------------------------------------------- #
# Loader                                                                       #
# --------------------------------------------------------------------------- #

class PrecomputedKB:
    """Loader and validator for a pre-computed knowledge-base directory.

    Intended use:

        kb = PrecomputedKB(knowledge_root=Path("knowledge"))
        outcome = kb.validate(
            model_name="sentence-transformers/paraphrase-multilingual-mpnet-base-v2",
            chunker_source_path=Path("core/ingest/chunking.py"),
            ingest_source_path=Path("core/ingest/ingest_knowledge.py"),
        )
        if outcome.ok:
            entries = kb.load_entries(lang="ca")
            # feed entries to Qdrant upsert
        else:
            logger.warning("precomputed invalid: %s — falling back", outcome.reason)
    """

    def __init__(self, knowledge_root: Path):
        self.knowledge_root = Path(knowledge_root)
        self.embeddings_dir = self.knowledge_root / EMBEDDINGS_SUBDIR
        self.manifest_path = self.embeddings_dir / MANIFEST_FILENAME
        self._manifest_cache: Optional[Dict[str, Any]] = None

    # -- manifest I/O ------------------------------------------------------- #

    def exists(self) -> bool:
        return self.manifest_path.is_file()

    def load_manifest(self) -> Optional[Dict[str, Any]]:
        if self._manifest_cache is not None:
            return self._manifest_cache
        if not self.exists():
            return None
        try:
            data = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("precomputed manifest unreadable: %s", e)
            return None
        self._manifest_cache = data
        return data

    # -- validation --------------------------------------------------------- #

    def validate(
        self,
        *,
        model_name: str,
        chunker_source_path: Path,
        ingest_source_path: Path,
    ) -> ValidationOutcome:
        """Strict validation: returns ok=True only if every hash and
        version we care about matches. On mismatch, `reason` is a short
        human-readable string suitable for logging."""
        manifest = self.load_manifest()
        if manifest is None:
            return ValidationOutcome(False, reason="no manifest present")

        if manifest.get("schema_version") != SCHEMA_VERSION:
            return ValidationOutcome(
                False,
                reason=f"schema_version mismatch "
                f"(expected {SCHEMA_VERSION}, got {manifest.get('schema_version')})",
                manifest=manifest,
            )

        runtime = get_runtime_fingerprint(
            model_name=model_name,
            chunker_source_path=chunker_source_path,
            ingest_source_path=ingest_source_path,
        )

        checks = [
            ("fastembed_version", runtime["fastembed_version"]),
            ("onnxruntime_version", runtime["onnxruntime_version"]),
            ("model_name", runtime["model_name"]),
            ("model_hf_commit", runtime["model_hf_commit"]),
            ("chunker_source_sha256", runtime["chunker_source_sha256"]),
            ("prefix_format_version", runtime["prefix_format_version"]),
        ]
        for key, expected in checks:
            got = manifest.get(key)
            if expected is None or got is None:
                # Tolerate None on one side only if both are None (e.g.
                # hub cache layout not found on either). Otherwise fail.
                if not (expected is None and got is None):
                    return ValidationOutcome(
                        False,
                        reason=f"{key} missing on one side (manifest={got!r}, runtime={expected!r})",
                        manifest=manifest,
                    )
                continue
            if got != expected:
                return ValidationOutcome(
                    False,
                    reason=f"{key} mismatch (manifest={got!r}, runtime={expected!r})",
                    manifest=manifest,
                )

        # Per-lang source hash check so an edited MD invalidates its lang
        # without dragging the others down.
        langs = manifest.get("langs") or {}
        for lang, info in langs.items():
            lang_dir = self.knowledge_root / lang
            if not lang_dir.is_dir():
                # lang listed in manifest but folder deleted → stale
                return ValidationOutcome(
                    False,
                    reason=f"lang '{lang}' listed in manifest but folder missing",
                    manifest=manifest,
                )
            expected = info.get("source_sha256")
            got = sha256_of_source_dir(lang_dir)
            if expected != got:
                return ValidationOutcome(
                    False,
                    reason=f"source_sha256 mismatch for lang '{lang}'",
                    manifest=manifest,
                )

        return ValidationOutcome(True, manifest=manifest)

    # -- loading ------------------------------------------------------------ #

    def list_languages(self) -> List[str]:
        manifest = self.load_manifest() or {}
        return sorted((manifest.get("langs") or {}).keys())

    def load_entries(self, lang: str) -> List[PrecomputedEntry]:
        """Load every chunk for a language as PrecomputedEntry instances.

        Assumes `validate()` has already returned ok=True. Any I/O error
        here raises; the caller should not have reached this path unless
        validation succeeded.
        """
        manifest = self.load_manifest()
        if manifest is None:
            raise RuntimeError("load_entries() called before validate() or manifest missing")
        langs = manifest.get("langs") or {}
        if lang not in langs:
            raise KeyError(f"language '{lang}' not in manifest")

        vectors_path = self.embeddings_dir / VECTORS_FILENAME.format(lang=lang)
        metadata_path = self.embeddings_dir / METADATA_FILENAME.format(lang=lang)

        # Per-file hash check so on-disk corruption is caught before we
        # poison the Qdrant collection with garbage vectors.
        expected_v = langs[lang].get("vectors_sha256")
        expected_m = langs[lang].get("metadata_sha256")
        if expected_v and sha256_of_file(vectors_path) != expected_v:
            raise RuntimeError(f"vectors-{lang}.npz hash mismatch vs manifest")
        if expected_m and sha256_of_file(metadata_path) != expected_m:
            raise RuntimeError(f"metadata-{lang}.jsonl hash mismatch vs manifest")

        with np.load(vectors_path) as npz:
            vectors = npz["embeddings"]  # shape (N, dim), float32

        entries: List[PrecomputedEntry] = []
        with metadata_path.open("r", encoding="utf-8") as f:
            for i, line in enumerate(f):
                rec = json.loads(line)
                if i >= len(vectors):
                    raise RuntimeError(
                        f"metadata row {i} has no matching vector in {vectors_path.name}"
                    )
                entries.append(PrecomputedEntry(
                    text=rec["text"],
                    metadata=rec["metadata"],
                    collection=rec["collection"],
                    doc_id=rec.get("doc_id"),
                    embedding=vectors[i].tolist(),
                ))
        if len(entries) != len(vectors):
            raise RuntimeError(
                f"lang {lang}: {len(entries)} metadata rows vs {len(vectors)} vectors"
            )
        return entries

    def entries_grouped_by_collection(self, lang: str) -> Dict[str, List[PrecomputedEntry]]:
        out: Dict[str, List[PrecomputedEntry]] = {}
        for e in self.load_entries(lang):
            out.setdefault(e.collection, []).append(e)
        return out


__all__ = [
    "PrecomputedKB",
    "PrecomputedEntry",
    "ValidationOutcome",
    "SCHEMA_VERSION",
    "PREFIX_FORMAT_VERSION",
    "EMBEDDINGS_SUBDIR",
    "MANIFEST_FILENAME",
    "VECTORS_FILENAME",
    "METADATA_FILENAME",
    "get_runtime_fingerprint",
    "read_hf_model_commit",
    "sha256_of_source_dir",
    "sha256_of_file",
]
