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
from typing import Any, Optional

# Add project root to path
from core.paths import get_repo_root
PROJECT_ROOT = get_repo_root()
sys.path.insert(0, str(PROJECT_ROOT))

logger = logging.getLogger(__name__)

from core.endpoints.chat_sanitization import _filter_rag_injection  # noqa: E402
from memory.memory.constants import DEFAULT_VECTOR_SIZE  # noqa: E402
from memory.memory.config import resolve_ingest_config  # noqa: E402
from memory.memory.precomputed_loader import PrecomputedKB  # noqa: E402
from memory.rag.header_parser import parse_rag_header, VALID_PRIORITIES  # noqa: E402  # after sys.path setup

import os as _os  # noqa: E402  # after sys.path setup
_LANG = _os.environ.get("NEXE_LANG", "en")
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
    """Return the translated string for the given key and current language."""
    s = _I18N.get(key, {}).get(_LANG) or _I18N.get(key, {}).get("ca", key) or key
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


from core.ingest.chunking import chunk_text  # noqa: E402  # after sys.path setup


def _build_file_items(
    file_path: Path,
    ingest_cfg: Any,
    target_collection: str,
    log,
    perf_chunking_ns_ref: list,
) -> tuple[list, str, int]:
    """Parse a single file and return (batch_items, doc_collection, num_chunks).

    Reads the RAG header if present, chunks the content, and builds the
    metadata dict for each chunk. Pure function with no I/O side-effects
    beyond reading the file. perf_chunking_ns_ref is a 1-element list used
    as an accumulator so the caller can sum chunking time across files.
    """
    content = read_file(file_path)
    if not content:
        return [], target_collection, 0

    filename = file_path.name
    log(_t("processing_f", i="?", n="?", f=filename))

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
        if rag_header.validation_errors and rag_header.validation_errors != ["No RAG header found"]:
            log(_t("invalid_header", e=', '.join(rag_header.validation_errors[:2])))
        body_content = content
        doc_chunk_size = CHUNK_SIZE
        doc_collection = target_collection
        doc_priority = DEFAULT_PRIORITY
        doc_tags = []
        doc_abstract = ""
        doc_id = filename
        doc_type = DEFAULT_TYPE
        doc_lang = _os.environ.get("NEXE_LANG", "en").split("-")[0].lower()

    doc_overlap = max(DEFAULT_OVERLAP_FLOOR, doc_chunk_size // DEFAULT_OVERLAP_FACTOR)

    _t0_chunk = time.perf_counter_ns()
    chunks = chunk_text(body_content, chunk_size=doc_chunk_size, overlap=doc_overlap)
    perf_chunking_ns_ref[0] += time.perf_counter_ns() - _t0_chunk

    priority_weight = 4 - VALID_PRIORITIES.index(doc_priority) if doc_priority in VALID_PRIORITIES else 2
    header_text = f"[Document: {filename}]\n"
    if doc_abstract:
        header_text += f"[Abstract: {doc_abstract}]\n"
    header_text += "\n"

    batch_items = [
        {
            "text": header_text + _filter_rag_injection(chunk),
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
        }
        for i, chunk in enumerate(chunks)
    ]
    return batch_items, doc_collection, len(chunks)


async def _flush_legacy_batch(memory, batch_items: list, doc_collection: str, num_chunks: int, batch_size: int, log) -> int:
    """Store batch_items in legacy mode (batched with single-store fallback). Returns chunks stored."""
    total = 0
    for b_start in range(0, len(batch_items), batch_size):
        batch = batch_items[b_start:b_start + batch_size]
        try:
            await memory.store_batch(batch, collection=doc_collection)
            total += len(batch)
        except Exception:
            for item in batch:
                await memory.store(text=item["text"], collection=doc_collection, metadata=item["metadata"])
                total += 1
        if num_chunks > 5 and (b_start + batch_size) <= len(batch_items):
            log(_t("chunks_progress", i=min(b_start + batch_size, num_chunks), n=num_chunks))
    return total


async def _flush_mega_batch(memory, mega_items_by_collection: dict, log) -> None:
    """Flush all accumulated mega-batch items (Bug #16). One store_batch per collection."""
    for coll, items in mega_items_by_collection.items():
        if not items:
            continue
        try:
            await memory.store_batch(items, collection=coll)
        except Exception as e:
            log(f"       [WARN] mega_batch fallback for {coll}: {e}")
            for item in items:
                try:
                    await memory.store(text=item["text"], collection=coll, metadata=item["metadata"])
                except Exception as e2:
                    log(f"       [ERROR] chunk failed: {e2}")


def _emit_perf_log(perf_record: dict) -> None:
    """Emit structured [PERF_INGEST] line to stdout and logger (Bug #16)."""
    line = "[PERF_INGEST] " + json.dumps(perf_record, ensure_ascii=False)
    print(line, flush=True)
    logger.info(line)


def _read_text_with_fallback(file_path: Path) -> str:
    """Reads text with encoding fallback.

    Bug 18 (2026-04-06) — previously `read_text(encoding="utf-8")` raised
    UnicodeDecodeError for latin-1/cp1252 files and they were silently ignored
    (ingests ended up with lost chunks without any warning). Now we try a
    chain of common encodings and warn via logger.info when not UTF-8.
    """
    # Dev D (Consultant pass 1): cp1252 BEFORE latin-1. latin-1 accepts
    # all bytes 0-255 by construction, so it would never fall through to cp1252
    # if it came first. Windows-1252 smart quotes/em-dashes would appear
    # as invisible control characters. By trying cp1252 first we preserve
    # that fidelity for real Windows files.
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


def _resolve_knowledge_path(folder, lang) -> Path:
    """Resolve the knowledge folder path, preferring a language-specific subdirectory."""
    knowledge_path = folder or PROJECT_ROOT / "knowledge"
    lang_path = knowledge_path / lang
    if lang_path.is_dir():
        return lang_path
    return knowledge_path


def _discover_documents(knowledge_path) -> list[Path]:
    """Discover all supported documents recursively under the knowledge path."""
    files: list[Path] = []
    for ext in SUPPORTED_EXTENSIONS:
        files.extend(knowledge_path.glob(f"**/*{ext}"))
    files.extend(knowledge_path.glob("**/*.pdf"))
    return [f for f in files if not f.name.startswith('.')]


def _print_ingestion_header(files) -> None:
    logger.info(_t("found_docs", n=len(files)))
    for f in files:
        logger.info("       - %s", f.name)


async def _initialize_memory() -> "Any":
    """Create and initialize a MemoryAPI instance."""
    from memory.memory.api import MemoryAPI
    memory = MemoryAPI()
    await memory.initialize()
    return memory


async def _ensure_collection(memory, target_collection, log) -> bool:
    """Ensure the target Qdrant collection exists, creating it if needed."""
    log(_t("preparing_col", c=target_collection))
    try:
        if not await memory.collection_exists(target_collection):
            await memory.create_collection(target_collection, vector_size=DEFAULT_VECTOR_SIZE)
        log(_t("col_ready", c=target_collection))
        return True
    except Exception as e:
        log(_t("col_error", e=e))
        return False


async def _try_precomputed_kb(memory, default_root, lang, log) -> bool:
    """Attempt to load a precomputed knowledge base, returning True on success."""
    try:
        _kb = PrecomputedKB(default_root)
        if _kb.exists():
            _outcome = _kb.validate(
                model_name=memory.embedding_model,
                chunker_source_path=PROJECT_ROOT / "core" / "ingest" / "chunking.py",
                ingest_source_path=PROJECT_ROOT / "core" / "ingest" / "ingest_knowledge.py",
            )
            if _outcome.ok and lang in _kb.list_languages():
                return await _ingest_from_precomputed(
                    memory=memory, kb=_kb, lang=lang, log=log,
                )
            elif not _outcome.ok:
                log(f"[INFO] precomputed KB skipped: {_outcome.reason}")
    except Exception as e:
        log(f"[INFO] precomputed KB error, falling back: {e}")
    return False


async def _process_file_batch(memory, files, target_collection, ingest_cfg, mega_batch_on, log) -> tuple[int, dict[str, list[dict[str, Any]]], int]:
    """Process all files for ingestion, returning chunk count, batched items, and chunking time."""
    total_chunks = 0
    mega_items_by_collection: dict[str, list[dict[str, Any]]] = {}
    _perf_chunking_ref = [0]

    for idx, file_path in enumerate(files, 1):
        try:
            log(_t("processing_f", i=idx, n=len(files), f=file_path.name))
            batch_items, doc_collection, num_chunks = _build_file_items(
                file_path, ingest_cfg, target_collection, log, _perf_chunking_ref,
            )
            if not batch_items:
                continue

            if mega_batch_on:
                mega_items_by_collection.setdefault(doc_collection, []).extend(batch_items)
                total_chunks += num_chunks
            else:
                stored = await _flush_legacy_batch(
                    memory, batch_items, doc_collection, num_chunks, ingest_cfg.store_batch_size, log,
                )
                total_chunks += stored

            log(_t("completed", n=num_chunks))
        except Exception as e:
            log(f"       [ERROR] {file_path.name}: {e}")

    return total_chunks, mega_items_by_collection, _perf_chunking_ref[0]


def _emit_final_summary(files, total_chunks, target_collection, log) -> None:
    """Print the final ingestion summary with document and chunk counts."""
    log(f"\n{'='*60}")
    log(_t("ingestion_done"))
    log(_t("docs_processed", n=len(files)))
    log(_t("total_chunks", n=total_chunks))
    log(_t("collection", c=target_collection))
    log(_t("ask_now"))
    log(f"{'='*60}\n")


def _emit_precomputed_perf_log(ingest_cfg, _perf_t0_ns: int, _perf_model_init_ns: int) -> None:
    """Emit perf log for the precomputed path (Bug #16)."""
    if not ingest_cfg.perf_logging:
        return
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


def _emit_full_ingest_perf_log(
    ingest_cfg,
    files,
    total_chunks: int,
    target_collection: str,
    _perf_t0_ns: int,
    _perf_model_init_ns: int,
    _perf_chunking_ns: int,
    _perf_snap,
) -> None:
    """Emit detailed perf log after full ingest run (Bug #16)."""
    if not ingest_cfg.perf_logging:
        return
    _perf_record: dict[str, Any] = {
        "event": "ingest_complete",
        "schema_version": 1,
        "bug": 16,
        "docs_processed": len(files),
        "total_chunks": total_chunks,
        "target_collection": target_collection,
        "lang": _LANG,
        "total_ns": time.perf_counter_ns() - _perf_t0_ns,
        "model_init_ns": _perf_model_init_ns,
        "chunking_ns": _perf_chunking_ns,
    }
    if _perf_snap is not None:
        _perf_record.update({k: _perf_snap.get(k, 0) for k in (
            "embed_ns", "embed_calls", "chunks_embedded",
            "store_total_ns", "store_calls", "chunks_stored",
            "warmup_ns", "upsert_ns_derived",
        )})
    _emit_perf_log(_perf_record)


async def _ingest_initialize_memory_and_config(log):
    """Initialize memory API, resolve ingest config, and pre-warm if needed.

    Returns (memory, ingest_cfg, _perf_model_init_ns) or raises on connection failure.
    """
    log(f"\n{_t('connecting')}")
    _perf_t_init_ns = time.perf_counter_ns()
    try:
        memory = await _initialize_memory()
    except Exception as e:
        log(_t("conn_error", e=e))
        log(_t("ensure_running"))
        raise
    _perf_model_init_ns = time.perf_counter_ns() - _perf_t_init_ns

    ingest_cfg = resolve_ingest_config(memory)
    getattr(memory, "reset_perf_counters", lambda: None)()
    if ingest_cfg.pre_warm:
        await memory.warmup()

    return memory, ingest_cfg, _perf_model_init_ns


async def ingest_knowledge(
    folder: Optional[Path] = None,
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
    def log(msg):
        if not quiet:
            logger.info("%s", msg)

    knowledge_path = _resolve_knowledge_path(folder, _LANG)

    log(f"\n{'='*60}")
    log(_t("title"))
    log(_t("add_docs"))
    log(f"{'='*60}\n")

    if not knowledge_path.exists():
        knowledge_path.mkdir(parents=True)
        log(f"[INFO] {_t('folder_created', p=knowledge_path)}")
        log(f"       {_t('add_and_rerun')}")
        return True

    files = _discover_documents(knowledge_path)

    if not files:
        log(f"[INFO] {_t('no_docs', p=knowledge_path)}")
        log(f"       {_t('formats')}")
        log(f"\n       {_t('example')}")
        log("         cp ~/Documents/manual.pdf knowledge/")
        log("         python -m core.ingest.ingest_knowledge")
        return True

    _print_ingestion_header(files)

    # Bug #16 instrumentation: wall-clock starts after file listing and
    # before MemoryAPI creation.
    _perf_t0_ns = time.perf_counter_ns()

    try:
        memory, ingest_cfg, _perf_model_init_ns = await _ingest_initialize_memory_and_config(log)
    except Exception:
        return False

    _default_root = PROJECT_ROOT / "knowledge"
    _custom_folder = folder is not None and not str(knowledge_path).startswith(str(_default_root))
    _precomputed_used = False
    if not _custom_folder:
        _precomputed_used = await _try_precomputed_kb(memory, _default_root, _LANG, log)

    if _precomputed_used:
        _emit_precomputed_perf_log(ingest_cfg, _perf_t0_ns, _perf_model_init_ns)
        await memory.close()
        return True

    if not await _ensure_collection(memory, target_collection, log):
        return False

    log(_t("processing"))
    mega_batch_on = bool(ingest_cfg.mega_batch)
    total_chunks, mega_items_by_collection, _perf_chunking_ns = await _process_file_batch(
        memory, files, target_collection, ingest_cfg, mega_batch_on, log,
    )

    if mega_batch_on:
        await _flush_mega_batch(memory, mega_items_by_collection, log)

    # Bug #16: capture perf snapshot BEFORE close().
    _perf_snap = memory.get_perf_snapshot() if hasattr(memory, "get_perf_snapshot") else None

    await memory.close()

    _emit_final_summary(files, total_chunks, target_collection, log)

    _emit_full_ingest_perf_log(
        ingest_cfg, files, total_chunks, target_collection,
        _perf_t0_ns, _perf_model_init_ns, _perf_chunking_ns, _perf_snap,
    )

    return True


if __name__ == "__main__":
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    success = asyncio.run(ingest_knowledge(folder))
    sys.exit(0 if success else 1)
