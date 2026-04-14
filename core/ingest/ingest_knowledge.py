#!/usr/bin/env python3
"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/ingest/ingest_knowledge.py
Description: Ingest user documents into Qdrant for personalized RAG.
             Users put their documents in knowledge/ folder.

Usage:
    python -m core.ingest.ingest_knowledge
    # Or via CLI:
    ./nexe knowledge ingest

Supported formats: .txt, .md, .pdf (requires pypdf)

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import asyncio
import json
import logging
import sys
import time
from pathlib import Path

# Add project root to path
from core.paths import get_repo_root
PROJECT_ROOT = get_repo_root()
sys.path.insert(0, str(PROJECT_ROOT))

logger = logging.getLogger(__name__)

from core.endpoints.chat_sanitization import _filter_rag_injection  # noqa: E402
from memory.memory.constants import DEFAULT_VECTOR_SIZE  # noqa: E402
from memory.memory.config import resolve_ingest_config  # noqa: E402
from memory.memory.precomputed_loader import PrecomputedKB  # noqa: E402
from memory.rag.header_parser import parse_rag_header, VALID_PRIORITIES

import os as _os
_LANG = _os.environ.get("NEXE_LANG", "ca")
_I18N = {
    "title":          {"ca": "NEXE KNOWLEDGE INGESTION", "es": "NEXE KNOWLEDGE INGESTION", "en": "NEXE KNOWLEDGE INGESTION"},
    "add_docs":       {"ca": "Afegeix els teus documents a la carpeta 'knowledge/'", "es": "Añade tus documentos a la carpeta 'knowledge/'", "en": "Add your documents to the 'knowledge/' folder"},
    "folder_created": {"ca": "Carpeta '{p}' creada.", "es": "Carpeta '{p}' creada.", "en": "Folder '{p}' created."},
    "add_and_rerun":  {"ca": "Afegeix documents (.txt, .md, .pdf) i torna a executar.", "es": "Añade documentos (.txt, .md, .pdf) y vuelve a ejecutar.", "en": "Add documents (.txt, .md, .pdf) and run again."},
    "no_docs":        {"ca": "No hi ha documents a '{p}'", "es": "No hay documentos en '{p}'", "en": "No documents found in '{p}'"},
    "formats":        {"ca": "Formats suportats: .txt, .md, .pdf", "es": "Formatos soportados: .txt, .md, .pdf", "en": "Supported formats: .txt, .md, .pdf"},
    "example":        {"ca": "Exemple:", "es": "Ejemplo:", "en": "Example:"},
    "found_docs":     {"ca": "[1/4] Trobats {n} documents", "es": "[1/4] Encontrados {n} documentos", "en": "[1/4] Found {n} documents"},
    "connecting":     {"ca": "[2/4] Connectant amb Qdrant...", "es": "[2/4] Conectando con Qdrant...", "en": "[2/4] Connecting to Qdrant..."},
    "conn_error":     {"ca": "[ERROR] No s'ha pogut connectar amb Qdrant: {e}", "es": "[ERROR] No se pudo conectar con Qdrant: {e}", "en": "[ERROR] Could not connect to Qdrant: {e}"},
    "ensure_running": {"ca": "        Assegura't que el servidor està corrent: ./nexe go", "es": "        Asegúrate de que el servidor está corriendo: ./nexe go", "en": "        Make sure the server is running: ./nexe go"},
    "preparing_col":  {"ca": "[3/4] Preparant col·lecció '{c}'...", "es": "[3/4] Preparando colección '{c}'...", "en": "[3/4] Preparing collection '{c}'..."},
    "col_ready":      {"ca": "       Col·lecció '{c}' preparada.", "es": "       Colección '{c}' preparada.", "en": "       Collection '{c}' ready."},
    "col_error":      {"ca": "[ERROR] Error creant col·lecció: {e}", "es": "[ERROR] Error creando colección: {e}", "en": "[ERROR] Error creating collection: {e}"},
    "processing":     {"ca": "[4/4] Processant documents...", "es": "[4/4] Procesando documentos...", "en": "[4/4] Processing documents..."},
    "processing_f":   {"ca": "       [{i}/{n}] Processant {f}...", "es": "       [{i}/{n}] Procesando {f}...", "en": "       [{i}/{n}] Processing {f}..."},
    "rag_header":     {"ca": "              ├─ Capçalera RAG: id={id}, priority={p}", "es": "              ├─ Cabecera RAG: id={id}, priority={p}", "en": "              ├─ RAG header: id={id}, priority={p}"},
    "invalid_header": {"ca": "              ├─ ⚠️ Capçalera invàlida: {e}", "es": "              ├─ ⚠️ Cabecera inválida: {e}", "en": "              ├─ ⚠️ Invalid header: {e}"},
    "chunks_progress":{"ca": "              └─ {i}/{n} fragments processats...", "es": "              └─ {i}/{n} fragmentos procesados...", "en": "              └─ {i}/{n} chunks processed..."},
    "completed":      {"ca": "              ✓ Completat ({n} fragments)", "es": "              ✓ Completado ({n} fragmentos)", "en": "              ✓ Completed ({n} chunks)"},
    "ingestion_done": {"ca": "INGESTA COMPLETADA!", "es": "¡INGESTIÓN COMPLETADA!", "en": "INGESTION COMPLETE!"},
    "docs_processed": {"ca": "  - Documents processats: {n}", "es": "  - Documentos procesados: {n}", "en": "  - Documents processed: {n}"},
    "total_chunks":   {"ca": "  - Fragments totals: {n}", "es": "  - Fragmentos totales: {n}", "en": "  - Total chunks: {n}"},
    "collection":     {"ca": "  - Col·lecció: {c}", "es": "  - Colección: {c}", "en": "  - Collection: {c}"},
    "ask_now":        {"ca": "\nAra pots preguntar sobre els teus documents al chat!", "es": "\n¡Ya puedes preguntar sobre tus documentos en el chat!", "en": "\nYou can now ask about your documents in the chat!"},
}
def _t(key, **kwargs):
    s = _I18N.get(key, {}).get(_LANG) or _I18N.get(key, {}).get("ca", key)
    return s.format(**kwargs) if kwargs else s

# Collections
# - USER_KNOWLEDGE_COLLECTION: ad-hoc docs uploaded by users from the chat UI
# - DOCUMENTATION_COLLECTION: corporate know-how ingested from the `knowledge/`
#   folder during install/post-install. The default target for this script
#   (was wrongly defaulting to user_knowledge before the F7 fix).
USER_KNOWLEDGE_COLLECTION = "user_knowledge"
DOCUMENTATION_COLLECTION = "nexe_documentation"
CHUNK_SIZE = 1500
CHUNK_OVERLAP = 200

# Defaults applied when a KB file has no (or invalid) RAG header.
# Extracted as module-level constants so offline tooling (notably
# `scripts/precompute_kb.py`) can reuse the same values without
# silently drifting. Any code path that produces embeddings must
# import from here — changing these invalidates the pre-computed
# manifest because chunker_source_sha256 covers the ingest source
# hash, which includes these defaults.
DEFAULT_PRIORITY = "P2"
DEFAULT_TYPE = "docs"
DEFAULT_OVERLAP_FACTOR = 10  # overlap = max(50, chunk_size // factor)
DEFAULT_OVERLAP_FLOOR = 50

# Supported file extensions
SUPPORTED_EXTENSIONS = {".txt", ".md", ".markdown", ".text"}


from core.ingest.chunking import chunk_text


def _read_text_with_fallback(file_path: Path) -> str:
    """Llegeix text amb fallback de codificació.

    Bug 18 (2026-04-06) — abans el `read_text(encoding="utf-8")` llançava
    UnicodeDecodeError per fitxers latin-1/cp1252 i s'ignoraven silenciosament
    (els ingests quedaven amb chunks perduts sense cap avís). Ara intentem una
    cadena d'encodings comuns i avisem via logger.info quan no és UTF-8.
    """
    # Dev D (Consultor passada 1): cp1252 ABANS de latin-1. latin-1 accepta
    # tots els bytes 0-255 per construcció, pel que mai cauria a cp1252 si
    # estigués abans. Els smart quotes/em-dashes de Windows-1252 quedarien
    # com a caràcters de control invisibles. Provant cp1252 primer guanyem
    # aquesta fidelitat pels fitxers Windows reals.
    encodings = ("utf-8", "utf-8-sig", "cp1252", "latin-1")
    last_err: UnicodeDecodeError | None = None
    for enc in encodings:
        try:
            content = file_path.read_text(encoding=enc)
            if enc != "utf-8":
                logger.info(
                    "File %s read with fallback encoding %s", file_path, enc
                )
            return content
        except UnicodeDecodeError as exc:
            last_err = exc
            continue
    logger.warning(
        "File %s could not be decoded with encodings %s: %s",
        file_path, encodings, last_err,
    )
    return ""


def read_file(file_path: Path) -> str:
    """Read file content based on extension."""
    ext = file_path.suffix.lower()

    if ext in {".txt", ".md", ".markdown", ".text"}:
        return _read_text_with_fallback(file_path)

    elif ext == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(file_path)
        text = ""
        for page in reader.pages:
            text += page.extract_text() + "\n"
        return text

    return ""


async def _ingest_from_precomputed(
    *,
    memory,
    kb: "PrecomputedKB",
    lang: str,
    default_collection: str,
    log,
) -> bool:
    """Bug #16 fast path: upsert pre-computed KB entries grouped by
    destination collection. Returns True on success, False on any
    failure (caller falls back to the embed pipeline).
    """
    try:
        grouped = kb.entries_grouped_by_collection(lang)
    except Exception as e:
        log(f"[WARN] precomputed load failed ({lang}): {e}")
        return False

    total = 0
    for collection, entries in grouped.items():
        try:
            if not await memory.collection_exists(collection):
                await memory.create_collection(collection, vector_size=DEFAULT_VECTOR_SIZE)
        except Exception as e:
            log(f"[WARN] precomputed create_collection failed ({collection}): {e}")
            return False

        # Match the legacy path: do NOT populate `doc_id` at the item
        # top level. The legacy ingest lets store_documents_batch derive
        # the Qdrant point id from a SHA256 hash of the text, and the
        # human-readable doc_id lives in `metadata["doc_id"]` for RAG
        # consumption. Passing a non-hex doc_id here would crash
        # hex_to_uuid in the underlying upsert.
        items = [
            {"text": e.text, "metadata": e.metadata}
            for e in entries
        ]
        embeddings = [e.embedding for e in entries]
        try:
            await memory.store_batch_precomputed(items, embeddings, collection=collection)
        except Exception as e:
            log(f"[WARN] precomputed store_batch failed ({collection}): {e}")
            return False
        total += len(items)
        log(f"[INFO] precomputed upserted {len(items)} chunks → {collection}")

    log(f"[INFO] precomputed path complete: {total} chunks, lang={lang}")
    return True


async def ingest_knowledge(
    folder: Path = None,
    quiet: bool = False,
    target_collection: str = DOCUMENTATION_COLLECTION,
):
    """Ingest user documents from knowledge/ folder into Qdrant.

    Args:
        folder: Path to knowledge folder (default: PROJECT_ROOT/knowledge)
        quiet: If True, suppress output (for auto-ingest at startup)
        target_collection: Destination collection (default: nexe_documentation,
            i.e. corporate know-how). Use "user_knowledge" only for ad-hoc docs
            uploaded by end users from the chat UI.
    """
    from memory.memory.api import MemoryAPI

    def log(msg):
        if not quiet:
            logger.info("%s", msg)

    knowledge_path = folder or PROJECT_ROOT / "knowledge"

    # Use language-specific subfolder if it exists (e.g. knowledge/ca/)
    lang_path = knowledge_path / _LANG
    if lang_path.is_dir():
        knowledge_path = lang_path

    log(f"\n{'='*60}")
    log(_t("title"))
    log(_t("add_docs"))
    log(f"{'='*60}\n")

    if not knowledge_path.exists():
        knowledge_path.mkdir(parents=True)
        log(f"[INFO] {_t('folder_created', p=knowledge_path)}")
        log(f"       {_t('add_and_rerun')}")
        return True

    # Find all supported files
    files = []
    for ext in SUPPORTED_EXTENSIONS:
        files.extend(knowledge_path.glob(f"**/*{ext}"))

    # Add PDF files
    pdf_files = list(knowledge_path.glob("**/*.pdf"))
    files.extend(pdf_files)

    # Filter out hidden files
    files = [f for f in files if not f.name.startswith('.')]

    if not files:
        log(f"[INFO] {_t('no_docs', p=knowledge_path)}")
        log(f"       {_t('formats')}")
        log(f"\n       {_t('example')}")
        log("         cp ~/Documents/manual.pdf knowledge/")
        log("         python -m core.ingest.ingest_knowledge")
        return True

    log(_t("found_docs", n=len(files)))
    for f in files:
        log(f"       - {f.name}")

    # Bug #16 instrumentation: wall-clock of the whole ingest phase starts
    # here, after file listing and before MemoryAPI creation. This matches
    # what end users experience during a cold install (see benchmark
    # harness in scripts/bench_ingest_bug16.py). When perf_logging is
    # disabled the local variables have negligible cost.
    _perf_t0_ns = time.perf_counter_ns()
    _perf_chunking_ns = 0

    # Initialize MemoryAPI
    log(f"\n{_t('connecting')}")
    _perf_t_init_ns = time.perf_counter_ns()
    memory = MemoryAPI()
    try:
        await memory.initialize()
    except Exception as e:
        log(_t("conn_error", e=e))
        log(_t("ensure_running"))
        return False
    _perf_model_init_ns = time.perf_counter_ns() - _perf_t_init_ns

    # Bug #16: read SSOT ingest config defensively so mocks without
    # ingest_config wired up keep working. Production MemoryAPI always
    # has a real IngestConfig attached (see memory/memory/config.py).
    ingest_cfg = resolve_ingest_config(memory)

    # Reset perf counters so this ingest run starts from a clean slate
    # (safe no-op if counters are already zero). Only matters when
    # perf_logging is True, but callable unconditionally.
    if hasattr(memory, "reset_perf_counters"):
        memory.reset_perf_counters()

    # Pre-warm embedder if enabled. Default pre_warm=False → skip entirely,
    # preserving historical call order to MemoryAPI.
    if ingest_cfg.pre_warm:
        await memory.warmup()

    # Bug #16: try the pre-computed KB fast path BEFORE running the
    # embedding pipeline. Only applies when the caller is ingesting the
    # default corporate KB (folder is None or inside PROJECT_ROOT/knowledge).
    # On any validation miss we fall through to the legacy embed path
    # below without altering its behaviour.
    _precomputed_used = False
    try:
        _default_root = PROJECT_ROOT / "knowledge"
        _custom_folder = folder is not None and not str(knowledge_path).startswith(str(_default_root))
        if not _custom_folder:
            _kb = PrecomputedKB(_default_root)
            if _kb.exists():
                _outcome = _kb.validate(
                    model_name=memory.embedding_model,
                    chunker_source_path=PROJECT_ROOT / "core" / "ingest" / "chunking.py",
                    ingest_source_path=PROJECT_ROOT / "core" / "ingest" / "ingest_knowledge.py",
                )
                if _outcome.ok and _LANG in _kb.list_languages():
                    _precomputed_used = await _ingest_from_precomputed(
                        memory=memory,
                        kb=_kb,
                        lang=_LANG,
                        default_collection=target_collection,
                        log=log,
                    )
                elif not _outcome.ok:
                    log(f"[INFO] precomputed KB skipped: {_outcome.reason}")
    except Exception as e:
        # Precomputed path is strictly an optimisation; any failure is
        # logged and we fall through to the embed pipeline.
        log(f"[INFO] precomputed KB error, falling back: {e}")

    if _precomputed_used:
        # Fast path already upserted everything and emitted its own
        # summary. Skip the legacy embed loop entirely.
        if ingest_cfg.perf_logging:
            _perf_total_ns = time.perf_counter_ns() - _perf_t0_ns
            _perf_record = {
                "event": "ingest_complete",
                "schema_version": 1,
                "bug": 16,
                "path": "precomputed",
                "lang": _LANG,
                "total_ns": _perf_total_ns,
                "model_init_ns": _perf_model_init_ns,
            }
            _perf_line = "[PERF_INGEST] " + json.dumps(_perf_record, ensure_ascii=False)
            print(_perf_line, flush=True)
            logger.info(_perf_line)
        await memory.close()
        return True

    # Ensure target collection exists (idempotent — F7 fix).
    # Previously this code did `delete_collection + create_collection` which
    # was destructive: re-running ingest wiped any user docs already stored
    # in the collection. Now we only create when missing.
    log(_t("preparing_col", c=target_collection))
    try:
        if not await memory.collection_exists(target_collection):
            await memory.create_collection(target_collection, vector_size=DEFAULT_VECTOR_SIZE)
        log(_t("col_ready", c=target_collection))
    except Exception as e:
        log(_t("col_error", e=e))
        return False

    # Ingest each file
    log(_t("processing"))
    total_chunks = 0

    # Bug #16 mega-batch: when enabled we accumulate items per collection
    # throughout the per-file loop and flush them all in a single
    # `store_batch()` per collection at the end. This amortises the
    # per-call setup cost of fastembed (measured ~1s/call) that dominates
    # the baseline. When disabled (default) the legacy per-file batching
    # is preserved bit-for-bit — parity is covered by
    # test_ingest_knowledge_mega_batch.py.
    mega_batch_on = bool(ingest_cfg.mega_batch)
    mega_items_by_collection: dict[str, list[dict]] = {}

    for idx, file_path in enumerate(files, 1):
        try:
            content = read_file(file_path)
            if not content:
                continue

            filename = file_path.name

            # Show progress indicator
            log(_t("processing_f", i=idx, n=len(files), f=filename))

            # Parse RAG header if present
            rag_header, body_content = parse_rag_header(content)

            if rag_header.is_valid:
                log(_t("rag_header", id=rag_header.id, p=rag_header.priority))
                doc_chunk_size = rag_header.chunk_size
                doc_collection = rag_header.collection or target_collection
                doc_priority = rag_header.priority
                doc_tags = rag_header.tags
                doc_abstract = rag_header.abstract
                doc_id = rag_header.id
                doc_type = rag_header.type
                doc_lang = rag_header.lang
            else:
                # No valid header - use defaults
                if rag_header.validation_errors and rag_header.validation_errors != ["No RAG header found"]:
                    log(_t("invalid_header", e=', '.join(rag_header.validation_errors[:2])))
                body_content = content  # Use full content
                doc_chunk_size = CHUNK_SIZE
                doc_collection = target_collection
                doc_priority = DEFAULT_PRIORITY
                doc_tags = []
                doc_abstract = ""
                doc_id = filename
                doc_type = DEFAULT_TYPE
                doc_lang = _os.environ.get("NEXE_LANG", "ca").split("-")[0].lower()

            # Calculate overlap based on chunk size
            doc_overlap = max(DEFAULT_OVERLAP_FLOOR, doc_chunk_size // DEFAULT_OVERLAP_FACTOR)

            # Add file header for context
            header_text = f"[Document: {filename}]\n"
            if doc_abstract:
                header_text += f"[Abstract: {doc_abstract}]\n"
            header_text += "\n"

            # Chunk the content using document-specific settings
            _perf_chunk_t0 = time.perf_counter_ns()
            chunks = chunk_text(body_content, chunk_size=doc_chunk_size, overlap=doc_overlap)
            _perf_chunking_ns += time.perf_counter_ns() - _perf_chunk_t0

            # Priority weight for search (P0=4, P1=3, P2=2, P3=1)
            priority_weight = 4 - VALID_PRIORITIES.index(doc_priority) if doc_priority in VALID_PRIORITIES else 2

            # Build batch items for all chunks.
            # Bug #16: BATCH_SIZE was hardcoded to 50 here. Now sourced from
            # the IngestConfig SSOT (default still 50 → behaviour-preserving).
            BATCH_SIZE = ingest_cfg.store_batch_size
            batch_items = []
            for i, chunk in enumerate(chunks):
                chunk = _filter_rag_injection(chunk)
                batch_items.append({
                    "text": header_text + chunk,
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

            if mega_batch_on:
                # Defer storage: accumulate per destination collection and
                # flush once, after the per-file loop has built every item.
                mega_items_by_collection.setdefault(doc_collection, []).extend(batch_items)
                total_chunks += len(batch_items)
                log(_t("completed", n=len(chunks)))
                continue

            # Legacy path: store in batches (with fallback to single-store).
            for b_start in range(0, len(batch_items), BATCH_SIZE):
                batch = batch_items[b_start:b_start + BATCH_SIZE]
                try:
                    await memory.store_batch(batch, collection=doc_collection)
                    total_chunks += len(batch)
                except Exception:
                    # Fallback: store one by one
                    for item in batch:
                        await memory.store(
                            text=item["text"],
                            collection=doc_collection,
                            metadata=item["metadata"],
                        )
                        total_chunks += 1
                if len(chunks) > 5 and (b_start + BATCH_SIZE) <= len(batch_items):
                    log(_t("chunks_progress", i=min(b_start + BATCH_SIZE, len(chunks)), n=len(chunks)))

            log(_t("completed", n=len(chunks)))

        except Exception as e:
            log(f"       [ERROR] {file_path.name}: {e}")

    # Bug #16 mega-batch flush: one `store_batch` per collection holding
    # all accumulated items. Preserves per-item metadata and RAG priority.
    # Falls back to single-store on failure, matching the legacy safety net.
    if mega_batch_on and mega_items_by_collection:
        for coll, items in mega_items_by_collection.items():
            if not items:
                continue
            try:
                await memory.store_batch(items, collection=coll)
            except Exception as e:
                log(f"       [WARN] mega_batch fallback for {coll}: {e}")
                for item in items:
                    try:
                        await memory.store(
                            text=item["text"],
                            collection=coll,
                            metadata=item["metadata"],
                        )
                    except Exception as e2:
                        log(f"       [ERROR] chunk failed: {e2}")

    # Bug #16: capture perf snapshot BEFORE close() since close() may
    # reset internal state. Wall-clock is captured outside to include
    # close() in the total (user-observed duration).
    _perf_snap = memory.get_perf_snapshot() if hasattr(memory, "get_perf_snapshot") else None

    await memory.close()

    log(f"\n{'='*60}")
    log(_t("ingestion_done"))
    log(_t("docs_processed", n=len(files)))
    log(_t("total_chunks", n=total_chunks))
    log(_t("collection", c=target_collection))
    log(_t("ask_now"))
    log(f"{'='*60}\n")

    # Bug #16: emit structured perf record as a single JSON line prefixed
    # with [PERF_INGEST]. Benchmark harness parses this deterministically.
    # Gated by ingest_config.perf_logging so production runs stay quiet.
    if ingest_cfg.perf_logging:
        _perf_total_ns = time.perf_counter_ns() - _perf_t0_ns
        _perf_record = {
            "event": "ingest_complete",
            "schema_version": 1,
            "bug": 16,
            "docs_processed": len(files),
            "total_chunks": total_chunks,
            "target_collection": target_collection,
            "lang": _LANG,
            "total_ns": _perf_total_ns,
            "model_init_ns": _perf_model_init_ns,
            "chunking_ns": _perf_chunking_ns,
        }
        if _perf_snap is not None:
            _perf_record.update({
                "embed_ns": _perf_snap.get("embed_ns", 0),
                "embed_calls": _perf_snap.get("embed_calls", 0),
                "chunks_embedded": _perf_snap.get("chunks_embedded", 0),
                "store_total_ns": _perf_snap.get("store_total_ns", 0),
                "store_calls": _perf_snap.get("store_calls", 0),
                "chunks_stored": _perf_snap.get("chunks_stored", 0),
                "warmup_ns": _perf_snap.get("warmup_ns", 0),
                "upsert_ns_derived": _perf_snap.get("upsert_ns_derived", 0),
            })
        # Print to stdout (benchmark) AND logger (for installer log capture).
        _perf_line = "[PERF_INGEST] " + json.dumps(_perf_record, ensure_ascii=False)
        print(_perf_line, flush=True)
        logger.info(_perf_line)

    return True


if __name__ == "__main__":
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    success = asyncio.run(ingest_knowledge(folder))
    sys.exit(0 if success else 1)
