#!/usr/bin/env python3
"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy
Location: core/ingest/ingest_knowledge.py
Description: Ingest user documents into Qdrant for personalized RAG.
             Users put their documents in knowledge/ folder.

Usage:
    python -m core.ingest.ingest_knowledge
    # Or via CLI:
    ./nexe knowledge ingest

Supported formats: .txt, .md, .pdf (requires pypdf)

www.jgoy.net
────────────────────────────────────
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from personality.i18n.modular_i18n import ModularI18nManager
from memory.rag.header_parser import parse_rag_header, RAGHeader, VALID_PRIORITIES

# Collection for user knowledge
USER_KNOWLEDGE_COLLECTION = "user_knowledge"
CHUNK_SIZE = 500
CHUNK_OVERLAP = 50

# Supported file extensions
SUPPORTED_EXTENSIONS = {".txt", ".md", ".markdown", ".text"}

_I18N = None


def _get_i18n():
    global _I18N
    if _I18N is None:
        config_path = PROJECT_ROOT / "personality" / "server.toml"
        if not config_path.exists():
            config_path = PROJECT_ROOT / "server.toml"
        _I18N = ModularI18nManager(config_path, PROJECT_ROOT)
    return _I18N


def _t(key: str, fallback: str, **kwargs) -> str:
    try:
        i18n = _get_i18n()
        value = i18n.t(key, **kwargs)
        if value == key:
            return fallback.format(**kwargs) if kwargs else fallback
        return value
    except Exception:
        return fallback.format(**kwargs) if kwargs else fallback


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list:
    """Split text into overlapping chunks."""
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        if chunk.strip():
            chunks.append(chunk.strip())
        start = end - overlap
    return chunks


def read_file(file_path: Path) -> str:
    """Read file content based on extension."""
    ext = file_path.suffix.lower()

    if ext in {".txt", ".md", ".markdown", ".text"}:
        return file_path.read_text(encoding="utf-8")

    elif ext == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(file_path)
        text = ""
        for page in reader.pages:
            text += page.extract_text() + "\n"
        return text

    return ""


async def ingest_knowledge(folder: Path = None, quiet: bool = False):
    """Ingest user documents from knowledge/ folder into Qdrant.

    Args:
        folder: Path to knowledge folder (default: PROJECT_ROOT/knowledge)
        quiet: If True, suppress output (for auto-ingest at startup)
    """
    from memory.memory.api import MemoryAPI
    t = _t

    def log(msg):
        if not quiet:
            print(msg)

    knowledge_path = folder or PROJECT_ROOT / "knowledge"

    log(f"\n{'='*60}")
    log(t("core.ingest.title", "NEXE KNOWLEDGE INGESTION"))
    log(t("core.ingest.subtitle", "Add your documents to the 'knowledge/' folder"))
    log(f"{'='*60}\n")

    if not knowledge_path.exists():
        knowledge_path.mkdir(parents=True)
        log(t("core.ingest.folder_created", "[INFO] Folder '{path}' created.", path=knowledge_path))
        log(t("core.ingest.folder_hint", "       Add documents (.txt, .md, .pdf) and run again."))
        return True

    # Find all supported files
    files = []
    for ext in SUPPORTED_EXTENSIONS:
        files.extend(knowledge_path.glob(f"**/*{ext}"))

    # Add PDF files
    pdf_files = list(knowledge_path.glob("**/*.pdf"))
    files.extend(pdf_files)

    # Filter out README and hidden files
    files = [f for f in files if not f.name.startswith('.') and f.name != 'README.md']

    if not files:
        log(t("core.ingest.no_docs", "[INFO] No documents found in '{path}'", path=knowledge_path))
        log(t("core.ingest.supported_formats", "       Supported formats: .txt, .md, .pdf"))
        log(t("core.ingest.example_title", "\n       Example:"))
        log("         cp ~/Documents/manual.pdf knowledge/")
        log("         python -m core.ingest.ingest_knowledge")
        return True

    log(t("core.ingest.found_docs", "[1/4] Found {count} documents", count=len(files)))
    for f in files:
        log(f"       - {f.name}")

    # Initialize MemoryAPI
    log(t("core.ingest.connecting_qdrant", "\n[2/4] Connecting to Qdrant..."))
    memory = MemoryAPI()
    try:
        await memory.initialize()
    except Exception as e:
        log(t("core.ingest.qdrant_connect_error", "[ERROR] Could not connect to Qdrant: {error}", error=e))
        log(t("core.ingest.server_hint", "        Make sure the server is running: ./nexe go"))
        return False

    # Create/recreate collection
    log(t(
        "core.ingest.prepare_collection",
        "[3/4] Preparing collection '{collection}'...",
        collection=USER_KNOWLEDGE_COLLECTION
    ))
    try:
        if await memory.collection_exists(USER_KNOWLEDGE_COLLECTION):
            await memory.delete_collection(USER_KNOWLEDGE_COLLECTION)
        await memory.create_collection(USER_KNOWLEDGE_COLLECTION, vector_size=384)
        log(t(
            "core.ingest.collection_ready",
            "       Collection '{collection}' ready.",
            collection=USER_KNOWLEDGE_COLLECTION
        ))
    except Exception as e:
        log(t("core.ingest.collection_error", "[ERROR] Error creating collection: {error}", error=e))
        return False

    # Ingest each file
    log(t("core.ingest.processing_docs", "[4/4] Processing documents..."))
    total_chunks = 0

    for idx, file_path in enumerate(files, 1):
        try:
            content = read_file(file_path)
            if not content:
                continue

            filename = file_path.name

            # Show progress indicator
            log(t(
                "core.ingest.processing_file",
                "       [{current}/{total}] Processing {filename}...",
                current=idx,
                total=len(files),
                filename=filename
            ))

            # Parse RAG header if present
            rag_header, body_content = parse_rag_header(content)

            if rag_header.is_valid:
                log(t(
                    "core.ingest.rag_header",
                    "              ├─ RAG header: id={id}, priority={priority}",
                    id=rag_header.id,
                    priority=rag_header.priority
                ))
                doc_chunk_size = rag_header.chunk_size
                doc_collection = rag_header.collection or USER_KNOWLEDGE_COLLECTION
                doc_priority = rag_header.priority
                doc_tags = rag_header.tags
                doc_abstract = rag_header.abstract
                doc_id = rag_header.id
                doc_type = rag_header.type
                doc_lang = rag_header.lang
            else:
                # No valid header - use defaults
                if rag_header.validation_errors and rag_header.raw_header:
                    log(t(
                        "core.ingest.rag_header_invalid",
                        "              ├─ ⚠️ Invalid RAG header: {errors}",
                        errors=", ".join(rag_header.validation_errors[:2])
                    ))
                body_content = content  # Use full content
                doc_chunk_size = CHUNK_SIZE
                doc_collection = USER_KNOWLEDGE_COLLECTION
                doc_priority = "P2"
                doc_tags = []
                doc_abstract = ""
                doc_id = filename
                doc_type = "docs"
                doc_lang = "ca"

            # Calculate overlap based on chunk size
            doc_overlap = max(50, doc_chunk_size // 10)

            # Add file header for context
            header_text = f"[{t('core.ingest.document_label', 'Document')}: {filename}]\n"
            if doc_abstract:
                header_text += f"[{t('core.ingest.abstract_label', 'Abstract')}: {doc_abstract}]\n"
            header_text += "\n"

            # Chunk the content using document-specific settings
            chunks = chunk_text(body_content, chunk_size=doc_chunk_size, overlap=doc_overlap)

            # Priority weight for search (P0=4, P1=3, P2=2, P3=1)
            priority_weight = 4 - VALID_PRIORITIES.index(doc_priority) if doc_priority in VALID_PRIORITIES else 2

            for i, chunk in enumerate(chunks):
                await memory.store(
                    text=header_text + chunk,
                    collection=doc_collection,
                    metadata={
                        "source": filename,
                        "doc_id": doc_id,
                        "chunk": i + 1,
                        "total_chunks": len(chunks),
                        "type": doc_type,
                        "priority": doc_priority,
                        "priority_weight": priority_weight,
                        "tags": doc_tags,
                        "lang": doc_lang,
                        "abstract": doc_abstract[:200] if doc_abstract else ""
                    }
                )
                total_chunks += 1

                # Show chunk progress for large files
                if len(chunks) > 5 and (i + 1) % 5 == 0:
                    log(t(
                        "core.ingest.chunk_progress",
                        "              └─ {current}/{total} chunks processed...",
                        current=i + 1,
                        total=len(chunks)
                    ))

            log(t(
                "core.ingest.file_complete",
                "              ✓ Completed ({chunks} chunks)",
                chunks=len(chunks)
            ))

        except Exception as e:
            log(t(
                "core.ingest.file_error",
                "       [ERROR] {file}: {error}",
                file=file_path.name,
                error=e
            ))

    await memory.close()

    log(f"\n{'='*60}")
    log(t("core.ingest.done_title", "INGESTION COMPLETE!"))
    log(t("core.ingest.summary_docs", "  - Documents processed: {count}", count=len(files)))
    log(t("core.ingest.summary_chunks", "  - Total chunks: {count}", count=total_chunks))
    log(t(
        "core.ingest.summary_collection",
        "  - Collection: {collection}",
        collection=USER_KNOWLEDGE_COLLECTION
    ))
    log(t("core.ingest.done_prompt", "\nYou can now ask about your documents in chat!"))
    log(f"{'='*60}\n")

    return True


if __name__ == "__main__":
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    success = asyncio.run(ingest_knowledge(folder))
    sys.exit(0 if success else 1)
