"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/rag_header.py
Description: Porter for parse_rag_header so plugins never import memory/,
             and the chunk prefix every indexed chunk carries.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from __future__ import annotations

from typing import Any, Tuple


def parse_rag_header(content: str) -> Tuple[Any, str]:
    """Re-export. Import lives here so plugins/ does not touch memory/."""
    from memory.rag.header_parser import parse_rag_header as _parse
    return _parse(content)


def rag_chunk_prefix(filename: str, abstract: str = "") -> str:
    """The text put in front of every chunk before it is embedded.

    One definition for the two ingests — the knowledge base
    (`core/ingest/ingest_knowledge.py`) and uploads (`core/files/attach.py`,
    #1071) — so a chunk is found by what its document is about, not only by
    its own words. `abstract` is empty when the document has no valid RAG
    header: a made-up one (the first chars of the body) repeated on every
    chunk would only dilute the vector.
    """
    prefix = f"[Document: {filename}]\n"
    if abstract:
        prefix += f"[Abstract: {abstract}]\n"
    return prefix + "\n"
