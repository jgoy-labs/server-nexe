"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/files/loaders/pdf.py
Description: PDF loader — pypdf with the B026 glued-text retry and NFKC.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────

ADR-008 E3 (#1070): moved verbatim out of `FileHandler._extract_pdf_sync`
(which now delegates here) so the knowledge-folder ingest reads PDFs with the
same pipeline uploads always had. Its own reader had neither the layout retry
nor the NFKC pass. NAT's `pdf.py` was NOT ported: this one is better.
"""

from __future__ import annotations

import logging
from pathlib import Path

from core.files.loaders import register_loader

logger = logging.getLogger(__name__)


def looks_glued(text: str) -> bool:
    """B026: detect pypdf output that lost inter-word spaces.

    PDFs with non-standard font encodings come out as
    'véroInecesitatuempresahoymismo' — normal prose has ~15% spaces,
    glued text has almost none. Short texts are not judged (tables,
    headers and code pages legitimately have few spaces).
    """
    stripped = text.strip()
    if len(stripped) < 200:
        return False
    space_ratio = stripped.count(" ") / len(stripped)
    return space_ratio < 0.05


@register_loader([".pdf"], magic=[b"%PDF"])
def extract_pdf(file_path: Path) -> str:
    """Extract text from PDF (sync, CPU-bound).

    B026: pypdf's default extraction loses inter-word spaces and breaks
    ligatures on PDFs with non-standard encodings, poisoning the RAG index
    with unreadable text. Per page: if the default output looks glued,
    retry with extraction_mode="layout" (reconstructs spacing from glyph
    positions). The whole text is NFKC-normalized at the end — resolves
    ligature codepoints (ﬁ → fi) and recomposes decomposed accents (ı́ → í).
    """
    import re as _re
    import unicodedata as _ud
    from pypdf import PdfReader
    reader = PdfReader(file_path)
    total_pages = len(reader.pages)
    logger.info(f"PDF '{file_path.name}': {total_pages} pages, extracting...")
    pages = []
    relaid_count = 0
    for i, page in enumerate(reader.pages):
        page_text = page.extract_text() or ""
        if looks_glued(page_text):
            try:
                relaid = page.extract_text(extraction_mode="layout") or ""
                if relaid and not looks_glued(relaid):
                    # Layout mode pads columns with spaces — collapse runs.
                    page_text = _re.sub(r"[ \t]{2,}", " ", relaid)
                    relaid_count += 1
            except Exception as e:
                logger.debug(f"  PDF layout-mode retry failed on page {i + 1}: {e}")
        pages.append(page_text)
        if (i + 1) % 50 == 0:
            logger.info(f"  PDF: {i+1}/{total_pages} pages")
    if relaid_count:
        logger.info(f"PDF '{file_path.name}': {relaid_count} glued page(s) re-extracted in layout mode")
    text = _ud.normalize("NFKC", "\n".join(pages) + "\n")
    logger.info(f"PDF '{file_path.name}': {total_pages} pages -> {len(text)} chars extracted")
    return text
