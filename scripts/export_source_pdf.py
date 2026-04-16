#!/usr/bin/env python3
"""Export server-nexe representative source code to PDF for legal deposit."""

import os
import sys
from pathlib import Path
from datetime import date

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, PageBreak, Preformatted
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER

PROJECT_ROOT = Path(__file__).parent.parent
OUTPUT_PATH = Path.home() / "Desktop" / "server-nexe_codi-font.pdf"

INCLUDE_DIRS = ["core", "plugins"]
INCLUDE_EXTS = {".py", ".js", ".css", ".html"}
EXCLUDE_PATTERNS = [
    "__pycache__", "/tests/", "test_", ".embeddings",
    ".venv", "node_modules", ".git",
]

VERSION = "0.9.7"
TODAY = date.today().isoformat()


def collect_files(root: Path) -> list[Path]:
    files = []
    for dir_name in INCLUDE_DIRS:
        dir_path = root / dir_name
        if not dir_path.exists():
            continue
        for f in sorted(dir_path.rglob("*")):
            if f.suffix not in INCLUDE_EXTS:
                continue
            rel = str(f.relative_to(root))
            if any(pat in rel for pat in EXCLUDE_PATTERNS):
                continue
            files.append(f)
    return files


def build_pdf(files: list[Path], root: Path, output: Path):
    doc = SimpleDocTemplate(
        str(output),
        pagesize=A4,
        leftMargin=1.5 * cm,
        rightMargin=1.5 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
    )

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "Title",
        parent=styles["Title"],
        fontSize=20,
        spaceAfter=0.3 * cm,
        alignment=TA_CENTER,
    )
    subtitle_style = ParagraphStyle(
        "Subtitle",
        parent=styles["Normal"],
        fontSize=11,
        textColor=colors.HexColor("#555555"),
        alignment=TA_CENTER,
        spaceAfter=0.2 * cm,
    )
    file_header_style = ParagraphStyle(
        "FileHeader",
        parent=styles["Normal"],
        fontSize=9,
        fontName="Helvetica-Bold",
        textColor=colors.HexColor("#ffffff"),
        backColor=colors.HexColor("#2d2d2d"),
        leftIndent=4,
        rightIndent=4,
        spaceBefore=0.4 * cm,
        spaceAfter=0,
        leading=16,
    )
    code_style = ParagraphStyle(
        "Code",
        parent=styles["Code"],
        fontSize=6.5,
        fontName="Courier",
        leading=9,
        leftIndent=0,
        spaceAfter=0,
        spaceBefore=0,
        wordWrap=None,
    )

    story = []

    # Cover page
    story.append(Spacer(1, 3 * cm))
    story.append(Paragraph("server-nexe", title_style))
    story.append(Paragraph(f"Versió {VERSION}", subtitle_style))
    story.append(Spacer(1, 0.5 * cm))
    story.append(Paragraph(
        "Codi font representatiu — Dipòsit legal / Registre de la Propietat Intel·lectual",
        subtitle_style,
    ))
    story.append(Paragraph(f"Data d'exportació: {TODAY}", subtitle_style))
    story.append(Spacer(1, 0.5 * cm))
    story.append(Paragraph(
        f"Fitxers inclosos: {len(files)} | Directoris: core/, plugins/",
        subtitle_style,
    ))
    story.append(Spacer(1, 0.5 * cm))
    story.append(Paragraph(
        "© Jordi Goy — Tots els drets reservats",
        subtitle_style,
    ))
    story.append(PageBreak())

    # Source files
    for i, f in enumerate(files):
        rel = str(f.relative_to(root))
        print(f"  [{i+1}/{len(files)}] {rel}")

        story.append(Paragraph(f"  {rel}", file_header_style))

        try:
            content = f.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            content = f"# Error llegint fitxer: {e}"

        # Truncate very large files
        lines = content.splitlines()
        truncated = False
        if len(lines) > 1500:
            lines = lines[:1500]
            truncated = True

        for line in lines:
            # Escape ReportLab special chars
            line = (
                line.replace("&", "&amp;")
                    .replace("<", "&lt;")
                    .replace(">", "&gt;")
                    .expandtabs(4)
            )
            # Truncate very long lines
            if len(line) > 120:
                line = line[:117] + "…"
            story.append(Preformatted(line, code_style))

        if truncated:
            story.append(Paragraph(
                f"  [... fitxer truncat a 1500 línies ...]",
                subtitle_style,
            ))

    doc.build(story)
    return output


def main():
    print(f"server-nexe — Export codi font PDF")
    print(f"Arrel: {PROJECT_ROOT}")
    print(f"Destí: {OUTPUT_PATH}")
    print()

    files = collect_files(PROJECT_ROOT)
    print(f"Fitxers trobats: {len(files)}")
    print()

    print("Generant PDF...")
    build_pdf(files, PROJECT_ROOT, OUTPUT_PATH)

    size_mb = OUTPUT_PATH.stat().st_size / 1024 / 1024
    print()
    print(f"✓ PDF generat: {OUTPUT_PATH}")
    print(f"  Mida: {size_mb:.1f} MB")
    print(f"  Fitxers: {len(files)}")


if __name__ == "__main__":
    main()
