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

from memory.rag.header_parser import parse_rag_header, RAGHeader, VALID_PRIORITIES

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

# Collection for user knowledge
USER_KNOWLEDGE_COLLECTION = "user_knowledge"
CHUNK_SIZE = 500
CHUNK_OVERLAP = 50

# Supported file extensions
SUPPORTED_EXTENSIONS = {".txt", ".md", ".markdown", ".text"}


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

    def log(msg):
        if not quiet:
            print(msg)

    knowledge_path = folder or PROJECT_ROOT / "knowledge"

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

    # Filter out README and hidden files
    files = [f for f in files if not f.name.startswith('.') and f.name != 'README.md']

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

    # Initialize MemoryAPI
    log(f"\n{_t('connecting')}")
    memory = MemoryAPI()
    try:
        await memory.initialize()
    except Exception as e:
        log(_t("conn_error", e=e))
        log(_t("ensure_running"))
        return False

    # Create/recreate collection
    log(_t("preparing_col", c=USER_KNOWLEDGE_COLLECTION))
    try:
        if await memory.collection_exists(USER_KNOWLEDGE_COLLECTION):
            await memory.delete_collection(USER_KNOWLEDGE_COLLECTION)
        await memory.create_collection(USER_KNOWLEDGE_COLLECTION, vector_size=384)
        log(_t("col_ready", c=USER_KNOWLEDGE_COLLECTION))
    except Exception as e:
        log(_t("col_error", e=e))
        return False

    # Ingest each file
    log(_t("processing"))
    total_chunks = 0

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
                doc_collection = rag_header.collection or USER_KNOWLEDGE_COLLECTION
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
            header_text = f"[Document: {filename}]\n"
            if doc_abstract:
                header_text += f"[Abstract: {doc_abstract}]\n"
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
                    log(_t("chunks_progress", i=i+1, n=len(chunks)))

            log(_t("completed", n=len(chunks)))

        except Exception as e:
            log(f"       [ERROR] {file_path.name}: {e}")

    await memory.close()

    log(f"\n{'='*60}")
    log(_t("ingestion_done"))
    log(_t("docs_processed", n=len(files)))
    log(_t("total_chunks", n=total_chunks))
    log(_t("collection", c=USER_KNOWLEDGE_COLLECTION))
    log(_t("ask_now"))
    log(f"{'='*60}\n")

    return True


if __name__ == "__main__":
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    success = asyncio.run(ingest_knowledge(folder))
    sys.exit(0 if success else 1)
