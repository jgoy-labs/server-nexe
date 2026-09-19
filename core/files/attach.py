"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/files/attach.py
Description: Attaching an uploaded document to a session — the door-neutral body.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────

C4.3 / D4: an attachment belongs to the SESSION, not to the door it arrived
through. Everything here moved verbatim out of `POST /ui/upload`
(`plugins/web_ui_module/api/routes_files.py`), which kept only what is
door-specific: its decorator, `require_ui_auth`, the rate limiter, the
`is_valid_session_id` 400, and the translation of `FILE_EXTRACT_FAILED`.

The one thing that could not travel is i18n: `get_message` lives in the web UI
plugin and `core/` may not import `plugins/` (the layering gate keeps that edge
at 0). So the extraction failure leaves here as a STABLE CODE and each door
phrases it — which is also what keeps the `/ui/upload` response byte-identical
to what it answered before this moved.

`attach_to_session` takes `file_handler` as a parameter rather than reaching for
one itself: it is a pure door-neutral body, and which `FileHandler` instance a
caller hands it is that caller's business.

C4.3-b: the instance itself is no longer the web UI module's alone.
`attach_file_handler` below builds it once in the core lifespan (same
idempotent-attach shape as `core.sessions.attach.attach_session_manager` and
`core.memory_facts.attach.attach_memory_helper`), so `/v1` can reach it
without importing `plugins/`.
"""

from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional
import logging
import os as _os

from fastapi import HTTPException

if TYPE_CHECKING:
    from core.files.handler import FileHandler

# R6-15 v1.0.4: tolerate absent security plugin (endpoints gated by their door).
try:
    from core.security.input_sanitizers import validate_string_input  # pyright: ignore[reportAssignmentType]
except ImportError:
    def validate_string_input(s, *a, **k):  # type: ignore[misc, no-redef]
        return s
from core.endpoints.chat_sanitization import _filter_rag_injection
# The RAG header parser through the core porter. Tolerated absent: the shim
# this replaced (`routes_files.py:34-37` via `routes.py:20-23`) fell back to
# None, and an upload without a header is a supported upload.
try:
    from core.rag_header import parse_rag_header
except ImportError:  # pragma: no cover - exercised by the manifest coverage test
    parse_rag_header = None  # type: ignore[assignment]
import core.memory_facts as memory_facts

logger = logging.getLogger(__name__)

#: The extraction failure the doors translate. A code, not a sentence: the web
#: UI answers it in the user's language, an API client gets the code.
FILE_EXTRACT_FAILED = "file_extract_failed"


# P1-4: speed-bump denylist for accidental uploads of sensitive files.
# NOT security — bypassed by trivial encoding (gzip, base64, xor, custom format).
# Protects against drag&drop accidents (user selects wrong file) and catches
# naive copy-paste of credentials files.
#
# Scan window is limited to the first 8KB as a design choice: these patterns
# always appear near the start of their respective files (/etc/passwd headers,
# PEM armor, credentials file keys). Expanding the window would cost CPU on
# every upload without improving coverage for naive cases.
_SENSITIVE_UPLOAD_PATTERNS = [
    # System (most specific /etc/passwd signature — UID 0 GID 0)
    b"root:x:0:0:",
    # PEM-armored private keys (universal, high-value)
    b"-----BEGIN RSA PRIVATE KEY-----",
    b"-----BEGIN OPENSSH PRIVATE KEY-----",
    b"-----BEGIN PRIVATE KEY-----",
    b"-----BEGIN EC PRIVATE KEY-----",
    b"-----BEGIN DSA PRIVATE KEY-----",
    b"-----BEGIN PGP PRIVATE KEY BLOCK-----",  # nosemgrep: detected-pgp-private-key-block — denylist detection pattern, not a real secret
    # API tokens relevant to the real stack (Anthropic / OpenAI / GitHub / Google)
    b"sk-ant-",       # Anthropic (Claude API + Claude Code CLI)
    b"sk-proj-",      # OpenAI project key (GPT, Codex CLI, Responses API)
    b"ghp_",          # GitHub personal access token (classic)
    b"github_pat_",   # GitHub fine-grained PAT
    b"AIzaSy",        # Google API key (Gemini, AI Studio, Cloud, Firebase)
]
_SENSITIVE_UPLOAD_SCAN_LIMIT = 8192  # bytes — first 8KB only, see design note above


def _detect_sensitive_upload(content: bytes) -> Optional[bytes]:
    """Scan the first 8KB of upload content for sensitive pattern markers.

    Returns the matched pattern if found, None otherwise.

    Speed-bump only — NOT security. Trivial to bypass with gzip, base64,
    xor, or custom encoding. The goal is to catch accidental drag&drop of
    local credentials files and naive copy-paste from forums, not
    determined adversaries.
    """
    if not content:
        return None
    head = content[:_SENSITIVE_UPLOAD_SCAN_LIMIT]
    for pat in _SENSITIVE_UPLOAD_PATTERNS:
        if pat in head:
            return pat
    return None


def _is_symlink_outside_uploads(file_path: Path) -> bool:
    """P1-C: Returns True if file_path is a symlink that points outside the uploads directory.

    Compares the realpath of the saved file with the realpath of its parent directory.
    If the file (or the symlink target) does not live inside the uploads directory,
    it is considered malicious and must be rejected.

    Attack vector: ln -s /etc/passwd evil.pdf → injected /etc/passwd into RAG.
    Directly testable pattern (same as _detect_sensitive_upload) because
    @limiter.limit rejects MagicMock.

    NOTE: Does not affect local models (MLX/llama.cpp/Ollama) that never go through /upload.
    """
    _real = _os.path.realpath(str(file_path))
    _uploads_real = _os.path.realpath(str(file_path.parent))
    return not _real.startswith(_uploads_real + _os.sep) and _real != _uploads_real


def _build_base_doc_metadata(filename: str, content_size: int) -> dict:
    """Build the base document metadata dict for an upload."""
    return {
        "filename": filename,
        "upload_type": "file",
        "size": content_size,
        "source": "web_ui",
    }


def _apply_rag_header_metadata(doc_metadata: dict, rag_header, body_content: str, filename: str) -> None:
    """Update doc_metadata in-place from a RAG header (valid or fallback simple)."""
    if rag_header.is_valid:
        doc_metadata.update({
            "doc_id": rag_header.id,
            "abstract": rag_header.abstract,
            "tags": rag_header.tags,
            "priority": rag_header.priority,
            "type": rag_header.type,
            "lang": rag_header.lang,
            "collection": rag_header.collection,
        })
        logger.info(f"RAG header found: id={rag_header.id}, priority={rag_header.priority}")
    else:
        # Simple metadata (without LLM — avoids blocking for MLX/Ollama)
        _lang = _os.getenv("NEXE_LANG", "en").split("-")[0]
        _stem = filename.rsplit(".", 1)[0].replace("_", " ").replace("-", " ")
        doc_metadata.update({
            "abstract": " ".join(body_content.split())[:300],
            "tags": [_stem],
            "priority": "P2",
            "type": "docs",
            "lang": _lang,
        })
        logger.info(f"No RAG header — metadata simple per '{filename}'")


async def _index_document_chunks(*, chunks, filename, session_id, metadata, app_state) -> dict:
    """Index the chunks for RAG, reporting failure instead of raising it (#893).

    save_document_chunks() walks into collection_exists()/create_collection()
    with no guard of its own, so a memory/ that is down surfaces here as a plain
    exception. The document is already attached to the conversation by the time
    this runs; what is at stake is only whether it will be searchable.
    """
    try:
        return await memory_facts.helper_for(app_state).save_document_chunks(
            chunks=chunks,
            filename=filename,
            session_id=session_id,
            metadata=metadata,
        )
    except Exception as e:
        logger.warning(
            "Document '%s' attached but NOT indexed (memory unavailable): %s",
            filename, e,
        )
        return {"success": False, "chunks_saved": 0, "message": str(e)}


def _compute_chunk_size(rag_header, body_content: str, filename: str) -> int:
    """Return chunk size: from RAG header if valid, else auto from doc length.

    Auto thresholds:
      < 20K chars  (~7 pages)    -> 800   (maximum precision)
      < 100K chars (~33 pages)   -> 1000
      < 300K chars (~100 pages)  -> 1200
      >= 300K chars (>100 pages) -> 1500  (very large docs)
    """
    if rag_header and rag_header.is_valid:
        return rag_header.chunk_size
    _doc_len = len(body_content)
    if _doc_len < 20_000:
        chunk_size = 800
    elif _doc_len < 100_000:
        chunk_size = 1000
    elif _doc_len < 300_000:
        chunk_size = 1200
    else:
        chunk_size = 1500
    logger.info(f"chunk_size auto={chunk_size} per {_doc_len} chars ({filename})")
    return chunk_size


async def attach_to_session(
    *, app_state, session_mgr, file_handler, filename: Optional[str],
    content: bytes, session_id: Optional[str],
) -> dict:
    """Save, extract, chunk, attach to the session and index — for any door.

    The caller has already read `content` (capped at MAX_FILE_SIZE, so the 413
    belongs to the door that holds the stream) and validated `session_id` if it
    has its own rule for it.

    Raises HTTPException(400) for a rejected upload; `FILE_EXTRACT_FAILED` is
    the one whose detail is a code rather than a sentence — see the module
    docstring.

    Returns the response body, unchanged from what `/ui/upload` has always
    answered.
    """
    # Security (P1-4): speed-bump denylist for sensitive content patterns.
    # See _detect_sensitive_upload docstring for the design tradeoff.
    _matched_pattern = _detect_sensitive_upload(content)
    if _matched_pattern:
        logger.warning(
            f"Upload rejected: sensitive pattern detected {_matched_pattern[:30]!r}"
        )
        raise HTTPException(
            status_code=400,
            detail="File content rejected: matches sensitive pattern denylist",
        )

    # Security: validate filename (path traversal, injection).
    #
    # `allow_html=True` for the same reason `validate` uses it at both chat
    # doors (#1043, kickoff 31/08 §2.3): "escapar és una protecció de
    # renderitzat, i viu on toca" — the UI escapes when painting, both in the
    # file preview (`nexe-files.js:243`, `escapeHtml`) and in the chat bubble
    # (`nexe-render.js`, whose renderer escapes raw HTML and refuses every
    # scheme but http/https/mailto). Every injection detector stays ON and
    # still raises: `<`, `>` and `&` in a name are refused with a 400 before
    # this line can escape anything.
    #
    # What the escaping actually did here was split the file in two. Only the
    # disk used the escaped name (`validate_file` and `save_file` below); the
    # session, the RAG metadata and the HTTP response have always carried the
    # RAW one. The one character that survived the detectors to be escaped is
    # the apostrophe, so `l'informe.pdf` landed on disk as `l&#x27;informe.pdf`
    # while the chat, the session and `GET /ui/files` disagreed about its name
    # — and in Catalan and Spanish an apostrophe in a filename is ordinary.
    # The response body is unchanged by this: it was already the raw name.
    safe_name = validate_string_input(
        filename or "", max_length=255, context="path", allow_html=True,
    )
    valid, error = file_handler.validate_file(safe_name, len(content), content_bytes=content)
    if not valid:
        raise HTTPException(status_code=400, detail=error)

    file_path = await file_handler.save_file(safe_name, content)

    # P1-C: Symlink check — the saved file must not be a symlink
    # that points outside the expected uploads directory.
    if _is_symlink_outside_uploads(file_path):
        file_handler.delete_file(file_path)
        raise HTTPException(
            status_code=400,
            detail="File rejected: symlink outside upload directory",
        )

    text = await file_handler.extract_text_async(file_path)
    if not text:
        file_handler.delete_file(file_path)
        raise HTTPException(status_code=400, detail=FILE_EXTRACT_FAILED)

    # Parse RAG header if available
    rag_header = None
    body_content = text
    doc_metadata = _build_base_doc_metadata(filename, len(content))

    if parse_rag_header:
        rag_header, body_content = parse_rag_header(text)
        _apply_rag_header_metadata(doc_metadata, rag_header, body_content, filename)

    chunk_size = _compute_chunk_size(rag_header, body_content, filename)
    # Security: filter injection patterns but do NOT truncate (chunking handles size)
    body_content = _filter_rag_injection(body_content)
    chunks = file_handler.chunk_text(body_content, chunk_size=chunk_size)
    logger.info(f"Document '{filename}': {len(body_content)} chars -> {len(chunks)} chunks (chunk_size={chunk_size})")

    # #893: attach to the session FIRST. The conversation needs memory/ for
    # nothing here, and indexing is the part that can fail — doing it first
    # made an optional dependency fatal for a function that is not, and cost
    # the user the document as well as the index. Same guarantee the chat
    # path already gives by writing the user's turn to disk before memory/
    # enters the scene.
    session = session_mgr.get_or_create_session(session_id)
    session.add_context_file(filename)

    # small=full, large=first 50 chunks (~30K tokens with 65K context)
    MAX_PREVIEW_CHUNKS = 50
    preview_chunks = chunks[:MAX_PREVIEW_CHUNKS]
    session.attach_document(filename, body_content, preview_chunks, total_chunks=len(chunks))
    session_mgr._save_session_to_disk(session)
    logger.info(f"Document '{filename}' attached ({len(preview_chunks)}/{len(chunks)} chunks)")

    # Index chunks in user_knowledge with session_id for cross-session
    # isolation. Degradable: what a broken memory/ costs is the search
    # index, and the answer says so via `ingested`.
    ingestion_result = await _index_document_chunks(
        app_state=app_state,
        chunks=chunks,
        filename=filename,
        session_id=session_id or "web_ui_upload",
        metadata=doc_metadata,
    )

    return {
        "filename": filename,
        "size": len(content),
        "text_length": len(text),
        "chunks": len(chunks),
        "preview": body_content[:500] + "..." if len(body_content) > 500 else body_content,
        "ingested": ingestion_result.get("success", False),
        "chunks_saved": ingestion_result.get("chunks_saved", 0),
        "session_id": session.id,
        "has_rag_header": rag_header.is_valid if rag_header else False
    }


def attach_file_handler(server_state: Any) -> "FileHandler":
    """Return the process-wide FileHandler, creating it once on server_state.

    Same idempotent-attach shape as core.sessions.attach.attach_session_manager
    and core.memory_facts.attach.attach_memory_helper. Until C4.3-b the web UI
    module built its own instance in its constructor; that made `attach_to_session`
    reachable only from `/ui`, since a second door had nowhere to get one without
    importing `plugins/`.
    """
    existing = getattr(server_state, "file_handler", None)
    if existing is not None:
        return existing

    from core.files.handler import FileHandler
    from core.paths.helpers import get_data_dir

    upload_dir = get_data_dir("uploads")
    handler = FileHandler(upload_dir)
    server_state.file_handler = handler
    logger.info("FileHandler attached (upload_dir=%s)", upload_dir)
    return handler
