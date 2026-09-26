"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/files/loaders/__init__.py
Description: Document loaders — the one registry of formats a document can
             arrive in, shared by uploads and the knowledge-folder ingest.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────

ADR-008 E3 (#1070): more formats are LOADERS AT INGESTION TIME, not a new
retrieval source. An upload is parsed once (`FileHandler.extract_text_async`),
chunked, embedded and stored in `user_knowledge`; retrieval only searches what
is already there. So a new format is one function registered here and nothing
else — no label, no prompt, no collection.

One source of truth. Before this package the list of formats lived in five
places (`handler.py`, `ingest_knowledge.py`, the CLI, the lifespan auto-ingest
and `scripts/precompute_kb.py`) and had already drifted: the knowledge ingest
read `.pdf` with a weaker reader than uploads did. Every one of them now asks
`supported_extensions()`.

A loader is a function `Path -> str` plus how its content is recognised:

* `magic` — the byte prefixes the file must start with (`%PDF`, the zip local
  header for the Office formats). Checked at upload time, before anything
  parses the file (SEC-004).
* no `magic` — a text format: the upload must be valid UTF-8.

Loaders raise `LoaderError` for content they cannot read; `extract_text`
turns anything else a third-party parser throws into one too, so callers deal
with a single failure type. `OSError` (a missing file) is left alone: that is
the caller's bug, not the document's.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, FrozenSet, Iterable, Optional, Tuple

logger = logging.getLogger(__name__)

#: Upload size cap — the doors read at most this many bytes (MC-078). Lives here
#: so the loaders can reuse it as their output cap without importing the handler
#: (which imports this package); `core.files.handler.MAX_FILE_SIZE` re-exports it.
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB

#: Most text a structured loader may produce (spreadsheets, CSV, Office, EPUB).
#: The same number as the upload cap, on purpose: a document never yields more
#: text than the largest plain-text upload could carry, so the chunker and the
#: embedder see nothing a `.txt` could not already send them. Not a second
#: limit — the first one, applied to what the file expands into.
MAX_EXTRACTED_CHARS = MAX_FILE_SIZE

#: Extensions that must never get a loader, whatever a future list says. `.env`,
#: `.conf`, `.ini`, `.cfg`, `.config` and `.properties` are where credentials
#: live; a pickle is code execution on load. Registering one raises at import.
EXCLUDED_EXTENSIONS: FrozenSet[str] = frozenset({
    ".env", ".pkl", ".pickle",
    ".conf", ".ini", ".cfg", ".config", ".properties",
})

#: Local file header of a zip archive — docx, xlsx, pptx and epub are all zips.
ZIP_MAGIC = b"PK\x03\x04"


class LoaderError(ValueError):
    """The file has a supported extension but its content cannot be read."""


class UnsupportedFormatError(LoaderError):
    """No loader is registered for this extension."""


@dataclass(frozen=True)
class Loader:
    func: Callable[[Path], str]
    #: Byte prefixes the content must start with; None means a UTF-8 text format.
    magic: Optional[Tuple[bytes, ...]] = None

    @property
    def is_text(self) -> bool:
        return self.magic is None


LOADER_REGISTRY: Dict[str, Loader] = {}


def register_loader(extensions: Iterable[str], *, magic: Optional[Iterable[bytes]] = None):
    """Register `func` as the loader for `extensions` (lower-cased, with dot).

    Refuses an excluded extension and a second loader for the same extension:
    both would be silent otherwise — the first a secrets file indexed for RAG,
    the second whichever module happened to import last winning.
    """
    magic_tuple = tuple(magic) if magic else None

    def decorator(func: Callable[[Path], str]) -> Callable[[Path], str]:
        for raw in extensions:
            ext = raw.lower()
            if ext in EXCLUDED_EXTENSIONS:
                raise ValueError(f"{ext} is excluded from document loading")
            if ext in LOADER_REGISTRY:
                raise ValueError(f"{ext} already has a loader: {LOADER_REGISTRY[ext].func.__name__}")
            LOADER_REGISTRY[ext] = Loader(func=func, magic=magic_tuple)
        return func

    return decorator


def supported_extensions() -> FrozenSet[str]:
    """Every extension a document may have — THE list, derived from the registry."""
    return frozenset(LOADER_REGISTRY)


def get_loader(file_path: Path | str) -> Optional[Loader]:
    return LOADER_REGISTRY.get(Path(file_path).suffix.lower())


def extract_text(file_path: Path) -> str:
    """Extract the text of `file_path` with the loader its extension names.

    Raises `UnsupportedFormatError` for an unregistered extension and
    `LoaderError` for content the loader cannot read. `OSError` propagates.
    """
    file_path = Path(file_path)
    loader = get_loader(file_path)
    if loader is None:
        raise UnsupportedFormatError(f"no loader for {file_path.suffix.lower() or '(no extension)'}")
    try:
        return loader.func(file_path)
    except (LoaderError, OSError):
        raise
    except Exception as e:  # a third-party parser's own exception zoo
        raise LoaderError(f"{file_path.name}: {type(e).__name__}: {e}") from e


class TextBudget:
    """Collects the parts of a structured document, refusing past the cap.

    Checked while the parts are produced, not after joining them, so a sheet
    with a million rows stops at the cap instead of first building the whole
    string in memory. Reads `MAX_EXTRACTED_CHARS` at construction, so the cap
    is the module's current value.
    """

    def __init__(self, sep: str = "\n") -> None:
        self.sep = sep
        self.limit = MAX_EXTRACTED_CHARS
        self.used = 0
        self.parts: list[str] = []

    def add(self, part: str) -> None:
        self.used += len(part) + len(self.sep)
        if self.used > self.limit:
            raise LoaderError(f"extracted text exceeds {self.limit} characters")
        self.parts.append(part)

    def text(self) -> str:
        return self.sep.join(self.parts)


# Import the loader modules so their decorators run. Order is irrelevant: a
# clash raises instead of letting the last import win.
from core.files.loaders import text as _text  # noqa: E402,F401
from core.files.loaders import data as _data  # noqa: E402,F401
from core.files.loaders import pdf as _pdf  # noqa: E402,F401
from core.files.loaders import office as _office  # noqa: E402,F401

__all__ = [
    "EXCLUDED_EXTENSIONS",
    "LOADER_REGISTRY",
    "Loader",
    "LoaderError",
    "MAX_EXTRACTED_CHARS",
    "MAX_FILE_SIZE",
    "TextBudget",
    "UnsupportedFormatError",
    "ZIP_MAGIC",
    "extract_text",
    "get_loader",
    "register_loader",
    "supported_extensions",
]
