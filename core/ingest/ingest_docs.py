#!/usr/bin/env python3
"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy
Location: core/ingest/ingest_docs.py
Description: Ingest documentation into Qdrant for RAG context.
             Run during installation or manually.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import asyncio
import logging
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logger = logging.getLogger(__name__)


DOCS_COLLECTION = "nexe_documentation"
CHUNK_SIZE = 500  # characters per chunk
CHUNK_OVERLAP = 50


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


async def ingest_documentation():
    """Ingest all documentation files into Qdrant."""
    from memory.memory.api import MemoryAPI

    docs_path = PROJECT_ROOT / "docs"
    readme_path = PROJECT_ROOT / "README.md"

    logger.info("Documentation ingestion started")

    # Initialize MemoryAPI
    logger.info("[1/4] Initializing MemoryAPI...")
    memory = MemoryAPI()
    try:
        await memory.initialize()
    except Exception as e:
        logger.error("[ERROR] Failed to initialize MemoryAPI: %s", e)
        logger.error("        Make sure Qdrant is running (./nexe go)")
        return False

    # Create collection if not exists
    logger.info("[2/4] Creating collection '%s'...", DOCS_COLLECTION)
    try:
        if not await memory.collection_exists(DOCS_COLLECTION):
            await memory.create_collection(DOCS_COLLECTION, vector_size=384)
            logger.info("       Collection '%s' created.", DOCS_COLLECTION)
        else:
            # Clear existing docs for fresh ingestion
            await memory.delete_collection(DOCS_COLLECTION)
            await memory.create_collection(DOCS_COLLECTION, vector_size=384)
            logger.info("       Collection '%s' recreated (fresh ingestion).", DOCS_COLLECTION)
    except Exception as e:
        logger.error("[ERROR] Failed to create collection: %s", e)
        return False

    # Find all markdown files
    logger.info("[3/4] Finding documentation files...")
    md_files = list(docs_path.glob("**/*.md"))
    if readme_path.exists():
        md_files.append(readme_path)

    logger.info("       Found %d documentation files.", len(md_files))

    # Ingest each file
    logger.info("[4/4] Ingesting documents...")
    total_chunks = 0
    for md_file in md_files:
        try:
            content = md_file.read_text(encoding="utf-8")
            filename = md_file.relative_to(PROJECT_ROOT)

            # Add file header for context
            header = f"[Document: {filename}]\n\n"

            # Chunk the content
            chunks = chunk_text(content)

            for i, chunk in enumerate(chunks):
                await memory.store(
                    text=header + chunk,
                    collection=DOCS_COLLECTION,
                    metadata={
                        "source": str(filename),
                        "chunk": i + 1,
                        "total_chunks": len(chunks),
                        "type": "documentation"
                    }
                )
                total_chunks += 1

            logger.info("       [OK] %s (%d chunks)", filename, len(chunks))

        except Exception as e:
            logger.error("       [ERROR] %s: %s", md_file.name, e)

    await memory.close()

    logger.info("Ingestion complete — files: %d, chunks: %d, collection: %s",
                len(md_files), total_chunks, DOCS_COLLECTION)

    return True


if __name__ == "__main__":
    success = asyncio.run(ingest_documentation())
    sys.exit(0 if success else 1)
