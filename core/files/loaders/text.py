"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/files/loaders/text.py
Description: Text-like loaders — plain text, markdown, source code, YAML, TOML.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────

ADR-008 E3 (#1070). Everything here is read as the text it already is: no
parser runs, so nothing in the file is ever executed or interpreted. YAML and
TOML are deliberately NOT parsed and re-dumped — a dump drops the comments and
reorders keys, and the comments are often the part worth retrieving.

Config-shaped extensions that usually hold secrets (`.env`, `.ini`, `.conf`,
`.cfg`, `.config`, `.properties`) are refused by the registry itself
(`EXCLUDED_EXTENSIONS`), not merely left out of this list.
"""

from __future__ import annotations

import logging
from pathlib import Path

from core.files.loaders import register_loader

logger = logging.getLogger(__name__)

#: Plain text and markdown — what uploads accepted before E3.
PLAIN_TEXT_EXTENSIONS = (".txt", ".md", ".markdown", ".text")

#: Source code, read as text. Adapted from NAT's `code.py`, minus its config
#: entries (see the module docstring), `.service`/`.vim`, and shell scripts:
#: `.sh`/`.bash`/`.zsh`/`.ps1` are where people keep `export TOKEN=...`, and
#: `tests/core/endpoints/test_security.py` pins `evil.sh` as refused. Adding
#: them is a decision to take on purpose, not a line to slip into this list.
CODE_EXTENSIONS = (
    ".py", ".pyi",
    ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx",
    ".html", ".htm", ".css", ".scss", ".sass",
    ".c", ".h", ".cpp", ".hpp", ".cc",
    ".java", ".kt", ".go", ".rs", ".php", ".rb", ".swift", ".lua",
    ".sql",
)

#: Structured text indexed as written (see the module docstring for why).
RAW_DATA_EXTENSIONS = (".yaml", ".yml", ".toml")

# Order matters: cp1252 BEFORE latin-1. latin-1 decodes every byte 0-255 by
# construction, so placed first it would never fall through to cp1252 and
# Windows-1252 smart quotes/em-dashes would come out as invisible control
# characters. `scripts/precompute_kb.py` embeds the knowledge folder through
# this same chain; changing it changes the pre-computed KB.
_ENCODINGS = ("utf-8", "utf-8-sig", "cp1252", "latin-1")


def read_text_with_fallback(file_path: Path) -> str:
    """Read text trying UTF-8 first, then the common Windows/legacy encodings.

    Bug 18 (2026-04-06): a bare `read_text(encoding="utf-8")` raised on
    latin-1/cp1252 files and the knowledge ingest dropped them without a word.
    Uploads are validated as UTF-8 before they get here, so for them the first
    attempt always succeeds; the chain is for the knowledge folder, where files
    arrive by copy and nobody checked them.

    Returns "" (with a warning) when nothing decodes; a missing file raises.
    """
    last_err: UnicodeDecodeError | None = None
    for enc in _ENCODINGS:
        try:
            content = file_path.read_text(encoding=enc)
            if enc != "utf-8":
                logger.info("File %s read with fallback encoding %s", file_path, enc)
            return content
        except UnicodeDecodeError as exc:
            last_err = exc
            continue
    logger.warning(
        "File %s could not be decoded with encodings %s: %s",
        file_path, _ENCODINGS, last_err,
    )
    return ""


@register_loader(PLAIN_TEXT_EXTENSIONS + CODE_EXTENSIONS + RAW_DATA_EXTENSIONS)
def load_text_file(file_path: Path) -> str:
    return read_text_with_fallback(file_path)
