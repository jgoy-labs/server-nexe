"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/plugins/web_ui_module/test_b026_pdf_extraction.py
Description: B026 — PDFs with non-standard font encodings produced glued text
    ("véroInecesitatuempresahoymismo") and broken ligatures, poisoning the RAG
    index. Tests: glued-detection heuristic, layout-mode retry per page, NFKC
    ligature normalization.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from plugins.web_ui_module.core.file_handler import FileHandler


GLUED = (
    "AgentesdeIAparatuempresahoymismo.Experimentaelpotencialconochoagentes"
    "preconfiguradosylistosparausar.Sinalucinacionesyconobjetivosdefinidos."
) * 3  # > 200 chars, ~0 spaces

PROSE = (
    "Els agents d'IA per a la teva empresa ja estan disponibles avui mateix. "
    "Experimenta el potencial amb vuit agents preconfigurats i llestos per usar. "
    "Sense al·lucinacions i amb objectius ben definits des del primer dia. "
) * 3


@pytest.fixture
def handler(tmp_path):
    return FileHandler(upload_dir=str(tmp_path))


class TestLooksGlued:
    def test_glued_text_detected(self):
        assert FileHandler._looks_glued(GLUED) is True

    def test_normal_prose_not_glued(self):
        assert FileHandler._looks_glued(PROSE) is False

    def test_short_text_never_judged(self):
        # Headers/tables legitimately have few spaces — don't relayout them.
        assert FileHandler._looks_glued("CAPITOL_1_INTRODUCCIO") is False

    def test_empty_text_not_glued(self):
        assert FileHandler._looks_glued("") is False


def _fake_page(default_text, layout_text=None):
    page = MagicMock()

    def _extract(extraction_mode=None):
        if extraction_mode == "layout":
            return layout_text if layout_text is not None else default_text
        return default_text

    page.extract_text = MagicMock(side_effect=_extract)
    return page


def _patch_reader(pages):
    reader = MagicMock()
    reader.pages = pages
    return patch("pypdf.PdfReader", return_value=reader)


class TestExtractPdfSync:
    def test_glued_page_reextracted_in_layout_mode(self, handler):
        page = _fake_page(GLUED, layout_text=PROSE + "   amb   espais   extra")
        with _patch_reader([page]):
            text = handler._extract_pdf_sync(Path("dummy.pdf"))
        assert "Els agents d'IA" in text
        # Layout-mode column padding collapsed to single spaces.
        assert "   " not in text
        page.extract_text.assert_any_call(extraction_mode="layout")

    def test_clean_page_not_relaid(self, handler):
        page = _fake_page(PROSE)
        with _patch_reader([page]):
            text = handler._extract_pdf_sync(Path("dummy.pdf"))
        assert "Els agents d'IA" in text
        # Only the default extraction ran — no layout retry for healthy pages.
        page.extract_text.assert_called_once_with()

    def test_layout_still_glued_keeps_default(self, handler):
        # If layout mode does not help, keep the default output (no regression).
        page = _fake_page(GLUED, layout_text=GLUED)
        with _patch_reader([page]):
            text = handler._extract_pdf_sync(Path("dummy.pdf"))
        assert GLUED[:60] in text

    def test_layout_exception_keeps_default(self, handler):
        page = MagicMock()

        def _extract(extraction_mode=None):
            if extraction_mode == "layout":
                raise RuntimeError("layout not supported for this page")
            return GLUED

        page.extract_text = MagicMock(side_effect=_extract)
        with _patch_reader([page]):
            text = handler._extract_pdf_sync(Path("dummy.pdf"))
        assert GLUED[:60] in text

    def test_nfkc_resolves_ligatures(self, handler):
        # U+FB01 (ﬁ) and U+FB02 (ﬂ) must come out as plain 'fi'/'fl'.
        page = _fake_page("la conﬁguració i el reﬂex " + PROSE)
        with _patch_reader([page]):
            text = handler._extract_pdf_sync(Path("dummy.pdf"))
        assert "configuració" in text
        assert "reflex" in text
        assert "ﬁ" not in text

    def test_extract_text_pdf_path_uses_same_pipeline(self, handler):
        page = _fake_page(GLUED, layout_text=PROSE)
        with _patch_reader([page]):
            text = handler.extract_text(Path("dummy.pdf"))
        assert "Els agents d'IA" in text
