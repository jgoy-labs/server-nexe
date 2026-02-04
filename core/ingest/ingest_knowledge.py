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
    log("NEXE KNOWLEDGE INGESTION")
    log("Afegeix els teus documents a la carpeta 'knowledge/'")
    log(f"{'='*60}\n")

    if not knowledge_path.exists():
        knowledge_path.mkdir(parents=True)
        log(f"[INFO] Carpeta '{knowledge_path}' creada.")
        log("       Afegeix documents (.txt, .md, .pdf) i torna a executar.")
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
        log(f"[INFO] No hi ha documents a '{knowledge_path}'")
        log("       Formats suportats: .txt, .md, .pdf")
        log("\n       Exemple:")
        log("         cp ~/Documents/manual.pdf knowledge/")
        log("         python -m core.ingest.ingest_knowledge")
        return True

    log(f"[1/4] Trobats {len(files)} documents")
    for f in files:
        log(f"       - {f.name}")

    # Initialize MemoryAPI
    log(f"\n[2/4] Connectant amb Qdrant...")
    memory = MemoryAPI()
    try:
        await memory.initialize()
    except Exception as e:
        log(f"[ERROR] No s'ha pogut connectar amb Qdrant: {e}")
        log("        Assegura't que el servidor està corrent: ./nexe go")
        return False

    # Create/recreate collection
    log(f"[3/4] Preparant col·lecció '{USER_KNOWLEDGE_COLLECTION}'...")
    try:
        if await memory.collection_exists(USER_KNOWLEDGE_COLLECTION):
            await memory.delete_collection(USER_KNOWLEDGE_COLLECTION)
        await memory.create_collection(USER_KNOWLEDGE_COLLECTION, vector_size=384)
        log(f"       Col·lecció '{USER_KNOWLEDGE_COLLECTION}' preparada.")
    except Exception as e:
        log(f"[ERROR] Error creant col·lecció: {e}")
        return False

    # Ingest each file
    log(f"[4/4] Processant documents...")
    total_chunks = 0

    for idx, file_path in enumerate(files, 1):
        try:
            content = read_file(file_path)
            if not content:
                continue

            filename = file_path.name

            # Show progress indicator
            log(f"       [{idx}/{len(files)}] Processant {filename}...")

            # Parse RAG header if present
            rag_header, body_content = parse_rag_header(content)

            if rag_header.is_valid:
                log(f"              ├─ Capçalera RAG: id={rag_header.id}, priority={rag_header.priority}")
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
                if rag_header.validation_errors and rag_header.validation_errors != ["No s'ha trobat capçalera RAG"]:
                    log(f"              ├─ ⚠️ Capçalera invàlida: {', '.join(rag_header.validation_errors[:2])}")
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
                    log(f"              └─ {i + 1}/{len(chunks)} fragments processats...")

            log(f"              ✓ Completat ({len(chunks)} fragments)")

        except Exception as e:
            log(f"       [ERROR] {file_path.name}: {e}")

    await memory.close()

    log(f"\n{'='*60}")
    log(f"INGESTA COMPLETADA!")
    log(f"  - Documents processats: {len(files)}")
    log(f"  - Fragments totals: {total_chunks}")
    log(f"  - Col·lecció: {USER_KNOWLEDGE_COLLECTION}")
    log(f"\nAra pots preguntar sobre els teus documents al chat!")
    log(f"{'='*60}\n")

    return True


if __name__ == "__main__":
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    success = asyncio.run(ingest_knowledge(folder))
    sys.exit(0 if success else 1)
