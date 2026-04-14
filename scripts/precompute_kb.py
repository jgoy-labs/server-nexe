#!/usr/bin/env python3
"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: scripts/precompute_kb.py
Description: Pre-compute KB embeddings offline (bug #16).

Runs the same chunking + prefix logic as `core/ingest/ingest_knowledge.py`
but emits per-chunk vectors to disk instead of upserting them. The
artefacts live under `knowledge/.embeddings/` and are git-tracked so
every install picks up the latest pre-computed set without any network
or compute during the cold path.

Usage:
    scripts/precompute_kb.py                     # all languages found
    scripts/precompute_kb.py --lang ca           # restrict to one lang
    scripts/precompute_kb.py --dry-run           # compute but don't write
    scripts/precompute_kb.py --verify            # compare on-disk vs fresh

The invariant that ties this script to the runtime loader is the
manifest produced here. Every field written to `manifest.json` is the
same one `precomputed_loader.PrecomputedKB.validate()` checks. If either
side changes, update both together.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np

# Ensure repo root is importable whatever cwd the user runs us from.
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from core.ingest.chunking import chunk_text  # noqa: E402
from core.endpoints.chat_sanitization import _filter_rag_injection  # noqa: E402
# Bug #16 SSOT: every default below lives in ingest_knowledge.py and is
# re-exported here so the precompute path never drifts from the runtime
# path. If a constant is missing here, ADD IT THERE and import, do not
# redefine locally.
from core.ingest.ingest_knowledge import (  # noqa: E402
    CHUNK_SIZE as DEFAULT_CHUNK_SIZE,
    DEFAULT_OVERLAP_FACTOR,
    DEFAULT_OVERLAP_FLOOR,
    DEFAULT_PRIORITY,
    DEFAULT_TYPE,
    DOCUMENTATION_COLLECTION as DEFAULT_COLLECTION,
    SUPPORTED_EXTENSIONS,
)
from memory.memory.constants import DEFAULT_EMBEDDING_MODEL  # noqa: E402
from memory.memory.precomputed_loader import (  # noqa: E402
    EMBEDDINGS_SUBDIR,
    MANIFEST_FILENAME,
    METADATA_FILENAME,
    PREFIX_FORMAT_VERSION,
    SCHEMA_VERSION,
    VECTORS_FILENAME,
    get_runtime_fingerprint,
    sha256_of_file,
    sha256_of_source_dir,
)
from memory.rag.header_parser import VALID_PRIORITIES, parse_rag_header  # noqa: E402

logger = logging.getLogger("precompute_kb")

KNOWLEDGE_ROOT = REPO_ROOT / "knowledge"
CHUNKER_SOURCE = REPO_ROOT / "core" / "ingest" / "chunking.py"
INGEST_SOURCE = REPO_ROOT / "core" / "ingest" / "ingest_knowledge.py"


# --------------------------------------------------------------------------- #
# Chunk building — MUST match ingest_knowledge.py semantics exactly           #
# --------------------------------------------------------------------------- #

def _read_text(path: Path) -> str:
    """Match ingest_knowledge.py's encoding fallback chain so the chunk
    text is byte-for-byte identical between this script and the runtime
    path."""
    for enc in ("utf-8", "utf-8-sig", "cp1252", "latin-1"):
        try:
            return path.read_text(encoding=enc)
        except UnicodeDecodeError:
            continue
    return ""


def _build_items_for_file(file_path: Path, target_collection: str, lang: str) -> List[Dict[str, Any]]:
    """Replicates ingest_knowledge.py's per-file loop body. Returned
    items carry the same keys (`text`, `metadata`, `doc_id`, `collection`)
    that store_batch would receive, plus the destination collection so we
    can fan out at load time."""
    content = _read_text(file_path)
    if not content:
        return []

    filename = file_path.name
    rag_header, body_content = parse_rag_header(content)

    if rag_header.is_valid:
        doc_chunk_size = rag_header.chunk_size
        doc_collection = rag_header.collection or target_collection
        doc_priority = rag_header.priority
        doc_tags = rag_header.tags
        doc_abstract = rag_header.abstract
        doc_id = rag_header.id
        doc_type = rag_header.type
        doc_lang = rag_header.lang
    else:
        body_content = content
        doc_chunk_size = DEFAULT_CHUNK_SIZE
        doc_collection = target_collection
        doc_priority = DEFAULT_PRIORITY
        doc_tags = []
        doc_abstract = ""
        doc_id = filename
        doc_type = DEFAULT_TYPE
        doc_lang = lang

    doc_overlap = max(DEFAULT_OVERLAP_FLOOR, doc_chunk_size // DEFAULT_OVERLAP_FACTOR)

    header_text = f"[Document: {filename}]\n"
    if doc_abstract:
        header_text += f"[Abstract: {doc_abstract}]\n"
    header_text += "\n"

    chunks = chunk_text(body_content, chunk_size=doc_chunk_size, overlap=doc_overlap)

    priority_weight = (
        4 - VALID_PRIORITIES.index(doc_priority)
        if doc_priority in VALID_PRIORITIES else 2
    )

    items: List[Dict[str, Any]] = []
    for i, chunk in enumerate(chunks):
        chunk = _filter_rag_injection(chunk)
        items.append({
            "text": header_text + chunk,
            "collection": doc_collection,
            "doc_id": doc_id,
            "metadata": {
                "source": filename,
                "doc_id": doc_id,
                "chunk": i + 1,
                "total_chunks": len(chunks),
                "type": doc_type,
                "priority": doc_priority,
                "priority_weight": priority_weight,
                "tags": doc_tags,
                "lang": doc_lang,
                "abstract": doc_abstract[:200] if doc_abstract else "",
            },
        })
    return items


def _collect_items_for_language(lang: str, *, verbose: bool = False) -> List[Dict[str, Any]]:
    lang_dir = KNOWLEDGE_ROOT / lang
    if not lang_dir.is_dir():
        return []
    files: List[Path] = []
    for ext in SUPPORTED_EXTENSIONS:
        files.extend(lang_dir.glob(f"**/*{ext}"))
    files.extend(lang_dir.glob("**/*.pdf"))
    files = sorted(f for f in files if not f.name.startswith("."))
    if verbose:
        logger.info("lang %s: %d files", lang, len(files))

    items: List[Dict[str, Any]] = []
    for f in files:
        if f.suffix.lower() == ".pdf":
            # Keep parity with ingest path: PDF handling needs pypdf and
            # isn't relevant to the static KB today. If we ever add a PDF
            # to knowledge/, extend here — for now warn and skip.
            logger.warning("skipping PDF (not yet supported in precompute): %s", f)
            continue
        items.extend(_build_items_for_file(f, DEFAULT_COLLECTION, lang))
    return items


# --------------------------------------------------------------------------- #
# Embedding                                                                    #
# --------------------------------------------------------------------------- #

def _embed_texts(texts: List[str], model_name: str) -> np.ndarray:
    """One-shot encode with fastembed + L2-normalise to match the runtime
    path (MemoryAPI._generate_embeddings_batch normalises the same way)."""
    from fastembed import TextEmbedding
    model = TextEmbedding(model_name)
    raw = list(model.embed(texts))
    arr = np.stack([np.asarray(v, dtype=np.float32) for v in raw])
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    # Avoid division by zero without silently altering well-formed rows.
    safe = np.where(norms > 0, norms, 1.0)
    arr = arr / safe
    return arr.astype(np.float32)


# --------------------------------------------------------------------------- #
# Manifest + artefact writing                                                  #
# --------------------------------------------------------------------------- #

def _write_artefacts(
    *,
    embeddings_dir: Path,
    lang: str,
    items: List[Dict[str, Any]],
    vectors: np.ndarray,
) -> Tuple[Path, Path, str, str]:
    """Emit `vectors-<lang>.npz` and `metadata-<lang>.jsonl`, return the
    paths plus their sha256 for inclusion in the manifest."""
    embeddings_dir.mkdir(parents=True, exist_ok=True)
    vectors_path = embeddings_dir / VECTORS_FILENAME.format(lang=lang)
    metadata_path = embeddings_dir / METADATA_FILENAME.format(lang=lang)

    np.savez_compressed(vectors_path, embeddings=vectors)
    with metadata_path.open("w", encoding="utf-8") as f:
        for it in items:
            f.write(json.dumps({
                "text": it["text"],
                "collection": it["collection"],
                "doc_id": it["doc_id"],
                "metadata": it["metadata"],
            }, ensure_ascii=False) + "\n")

    return vectors_path, metadata_path, sha256_of_file(vectors_path), sha256_of_file(metadata_path)


def _build_manifest(
    *,
    model_name: str,
    lang_info: Dict[str, Dict[str, Any]],
    vector_dim: int,
) -> Dict[str, Any]:
    fp = get_runtime_fingerprint(
        model_name=model_name,
        chunker_source_path=CHUNKER_SOURCE,
        ingest_source_path=INGEST_SOURCE,
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "prefix_format_version": PREFIX_FORMAT_VERSION,
        "vector_dim": vector_dim,
        "vector_dtype": "float32",
        **fp,
        "langs": lang_info,
    }


# --------------------------------------------------------------------------- #
# Entry point                                                                  #
# --------------------------------------------------------------------------- #

def _detect_languages() -> List[str]:
    if not KNOWLEDGE_ROOT.is_dir():
        return []
    return sorted(
        p.name for p in KNOWLEDGE_ROOT.iterdir()
        if p.is_dir() and not p.name.startswith(".") and p.name != EMBEDDINGS_SUBDIR
    )


def precompute(
    *,
    langs: List[str],
    model_name: str = DEFAULT_EMBEDDING_MODEL,
    dry_run: bool = False,
    verbose: bool = False,
) -> Dict[str, Any]:
    """Run the full precompute pipeline; return the manifest (written
    to disk unless dry_run)."""
    embeddings_dir = KNOWLEDGE_ROOT / EMBEDDINGS_SUBDIR
    lang_info: Dict[str, Dict[str, Any]] = {}
    total_chunks = 0

    for lang in langs:
        items = _collect_items_for_language(lang, verbose=verbose)
        if not items:
            logger.warning("lang %s: no chunks, skipping", lang)
            continue

        texts = [it["text"] for it in items]
        vectors = _embed_texts(texts, model_name)
        vector_dim = int(vectors.shape[1])

        logger.info("lang %s: %d chunks, %d-dim vectors", lang, len(items), vector_dim)
        total_chunks += len(items)

        if dry_run:
            continue

        _, _, v_sha, m_sha = _write_artefacts(
            embeddings_dir=embeddings_dir,
            lang=lang,
            items=items,
            vectors=vectors,
        )
        lang_info[lang] = {
            "chunks": len(items),
            "source_sha256": sha256_of_source_dir(KNOWLEDGE_ROOT / lang),
            "vectors_sha256": v_sha,
            "metadata_sha256": m_sha,
        }

    if dry_run:
        logger.info("dry-run: would have written %d chunks across %d langs", total_chunks, len(langs))
        return {}

    # Every written vector file is float32 and the same dim, so we can
    # pick any of them for the manifest top-level `vector_dim` field.
    first_lang = next(iter(lang_info), None)
    vector_dim = 0
    if first_lang:
        with np.load(embeddings_dir / VECTORS_FILENAME.format(lang=first_lang)) as npz:
            vector_dim = int(npz["embeddings"].shape[1])

    manifest = _build_manifest(
        model_name=model_name,
        lang_info=lang_info,
        vector_dim=vector_dim,
    )
    (embeddings_dir / MANIFEST_FILENAME).write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return manifest


def verify(model_name: str = DEFAULT_EMBEDDING_MODEL) -> bool:
    """Loads the current `.embeddings/` via PrecomputedKB and runs the
    same validation the runtime loader does. Returns True on success."""
    from memory.memory.precomputed_loader import PrecomputedKB
    kb = PrecomputedKB(KNOWLEDGE_ROOT)
    outcome = kb.validate(
        model_name=model_name,
        chunker_source_path=CHUNKER_SOURCE,
        ingest_source_path=INGEST_SOURCE,
    )
    if outcome.ok:
        logger.info("precomputed manifest valid")
        return True
    logger.error("precomputed invalid: %s", outcome.reason)
    return False


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pre-compute server-nexe KB embeddings (bug #16).")
    parser.add_argument("--lang", type=str, default=None,
                        help="Restrict to a single language folder (default: all detected).")
    parser.add_argument("--model", type=str, default=DEFAULT_EMBEDDING_MODEL,
                        help="Embedding model name (default matches production).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Compute but do not write artefacts.")
    parser.add_argument("--verify", action="store_true",
                        help="Validate existing .embeddings/ without re-computing.")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    if args.verify:
        return 0 if verify(args.model) else 1

    if args.lang:
        langs = [args.lang]
    else:
        langs = _detect_languages()

    if not langs:
        logger.error("no language directories found under %s", KNOWLEDGE_ROOT)
        return 2

    logger.info("precomputing langs: %s (model=%s)", ",".join(langs), args.model)
    precompute(langs=langs, model_name=args.model, dry_run=args.dry_run, verbose=args.verbose)
    logger.info("done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
