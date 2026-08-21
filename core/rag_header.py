"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/rag_header.py
Description: Porter for parse_rag_header so plugins never import memory/.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from __future__ import annotations

from typing import Any, Tuple


def parse_rag_header(content: str) -> Tuple[Any, str]:
    """Re-export. Import lives here so plugins/ does not touch memory/."""
    from memory.rag.header_parser import parse_rag_header as _parse
    return _parse(content)
