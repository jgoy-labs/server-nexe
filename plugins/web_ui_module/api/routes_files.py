"""
------------------------------------
Server Nexe
Location: plugins/web_ui_module/api/routes_files.py
Description: File upload and management endpoints.
             Extracted from routes.py during tech debt refactoring.

www.jgoy.net · https://server-nexe.org
------------------------------------
"""

from pathlib import Path
from typing import Optional
import logging
import os as _os
from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Depends, Request

from plugins.web_ui_module.messages import get_message, get_i18n
# R6-15 v1.0.4: tolerate absent security plugin (endpoints gated by require_ui_auth).
try:
    from plugins.security.core.input_sanitizers import validate_string_input
except ImportError:
    def validate_string_input(s, *a, **k):  # type: ignore[misc, no-redef]
        return s
from core.dependencies import limiter
from core.endpoints.chat_sanitization import _filter_rag_injection

def _get_memory_helper():
    """Lazy resolve via routes module so test patches work."""
    import plugins.web_ui_module.api.routes as _r
    return _r.get_memory_helper()

def _generate_rag_metadata(body_content, filename):
    """Lazy resolve via routes module so test patches work."""
    import plugins.web_ui_module.api.routes as _r
    return _r.generate_rag_metadata(body_content, filename)

def _get_parse_rag_header():
    """Lazy resolve parse_rag_header via routes module so test patches work."""
    import plugins.web_ui_module.api.routes as _r
    return _r.parse_rag_header

logger = logging.getLogger(__name__)


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
    b"-----BEGIN PGP PRIVATE KEY BLOCK-----",
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
        _lang = _os.getenv("NEXE_LANG", "ca").split("-")[0]
        _stem = filename.rsplit(".", 1)[0].replace("_", " ").replace("-", " ")
        doc_metadata.update({
            "abstract": " ".join(body_content.split())[:300],
            "tags": [_stem],
            "priority": "P2",
            "type": "docs",
            "lang": _lang,
        })
        logger.info(f"No RAG header — metadata simple per '{filename}'")


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


def register_file_routes(router: APIRouter, *, session_mgr, file_handler, require_ui_auth):
    """Registers endpoints: POST /upload, GET /files, DELETE /files/cleanup"""

    # -- POST /upload --

    @router.post("/upload", operation_id="webui_upload_file")
    @limiter.limit("5/minute")
    async def upload_file(
        request: Request,
        file: UploadFile = File(...),
        session_id: Optional[str] = Form(None),
        _auth=Depends(require_ui_auth),
        i18n=Depends(get_i18n),
    ):
        """Upload file and add to session context + automatic memory ingestion"""
        content = await file.read()

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

        # Security: validate filename (path traversal, injection)
        filename = validate_string_input(file.filename or "", max_length=255, context="path")
        valid, error = file_handler.validate_file(filename, len(content), content_bytes=content)
        if not valid:
            raise HTTPException(status_code=400, detail=error)

        file_path = await file_handler.save_file(filename, content)

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
            raise HTTPException(status_code=400, detail=get_message(i18n, "webui.file.extract_failed"))

        # Parse RAG header if available
        rag_header = None
        body_content = text
        doc_metadata = _build_base_doc_metadata(file.filename, len(content))

        parse_rag_header = _get_parse_rag_header()
        if parse_rag_header:
            rag_header, body_content = parse_rag_header(text)
            _apply_rag_header_metadata(doc_metadata, rag_header, body_content, file.filename)

        chunk_size = _compute_chunk_size(rag_header, body_content, file.filename)
        # Security: filter injection patterns but do NOT truncate (chunking handles size)
        body_content = _filter_rag_injection(body_content)
        chunks = file_handler.chunk_text(body_content, chunk_size=chunk_size)
        logger.info(f"Document '{file.filename}': {len(body_content)} chars -> {len(chunks)} chunks (chunk_size={chunk_size})")

        # Index chunks in user_knowledge with session_id for cross-session isolation
        memory_helper = _get_memory_helper()
        ingestion_result = await memory_helper.save_document_chunks(
            chunks=chunks,
            filename=file.filename,
            session_id=session_id or "web_ui_upload",
            metadata=doc_metadata,
        )

        # Attach to session
        session = session_mgr.get_or_create_session(session_id)
        session.add_context_file(file.filename)

        # Attach to session: small=full, large=first 50 chunks (~30K tokens with 65K context)
        MAX_PREVIEW_CHUNKS = 50
        preview_chunks = chunks[:MAX_PREVIEW_CHUNKS]
        session.attach_document(file.filename, body_content, preview_chunks, total_chunks=len(chunks))
        logger.info(f"Document '{file.filename}' attached ({len(preview_chunks)}/{len(chunks)} chunks) + RAG-ready")

        session_mgr._save_session_to_disk(session)

        return {
            "filename": file.filename,
            "size": len(content),
            "text_length": len(text),
            "chunks": len(chunks),
            "preview": body_content[:500] + "..." if len(body_content) > 500 else body_content,
            "ingested": ingestion_result.get("success", False),
            "chunks_saved": ingestion_result.get("chunks_saved", 0),
            "session_id": session.id,
            "has_rag_header": rag_header.is_valid if rag_header else False
        }

    # -- GET /files --

    @router.get("/files", operation_id="webui_list_files")
    async def list_uploaded_files(_auth=Depends(require_ui_auth)):
        """List all uploaded files"""
        files = file_handler.get_uploaded_files()
        return {"files": files, "total": len(files)}

    # -- POST /files/cleanup --

    @router.post("/files/cleanup", operation_id="webui_cleanup_files")
    @limiter.limit("5/minute")
    async def cleanup_files(request: Request, max_age_hours: int = 24, _auth=Depends(require_ui_auth)):
        """Clean up old files (default > 24h)"""
        deleted = file_handler.cleanup_old_files(max_age_hours)
        return {"deleted": deleted, "message": f"{deleted} files deleted"}
