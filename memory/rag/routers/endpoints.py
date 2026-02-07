"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: memory/rag/routers/endpoints.py
Description: API endpoints per mòdul RAG.

www.jgoy.net
────────────────────────────────────
"""

import json
import tempfile
import time
from pathlib import Path
from typing import Any, Dict

import structlog
from fastapi import Depends, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from plugins.security.core.auth import require_api_key
from personality.i18n import get_i18n

logger = structlog.get_logger()

_I18N = get_i18n()

def _t(key: str, fallback: str, **kwargs) -> str:
  """Translate with fallback using global i18n helper."""
  try:
    if _I18N:
      return _I18N.t(key, fallback, **kwargs)
  except Exception:
    pass
  if kwargs:
    try:
      return fallback.format(**kwargs)
    except (KeyError, ValueError):
      return fallback
  return fallback

_metrics_imported = False
_RAG_SEARCHES = None
_RAG_SEARCH_DURATION = None

def _get_metrics():
  """Lazy import Prometheus metrics."""
  global _metrics_imported, _RAG_SEARCHES, _RAG_SEARCH_DURATION
  if not _metrics_imported:
    try:
      from core.metrics.registry import RAG_SEARCHES, RAG_SEARCH_DURATION
      _RAG_SEARCHES = RAG_SEARCHES
      _RAG_SEARCH_DURATION = RAG_SEARCH_DURATION
      _metrics_imported = True
    except ImportError:
      _metrics_imported = True
  return _RAG_SEARCHES, _RAG_SEARCH_DURATION

def _get_file_rag():
  """Get singleton FileRAGSource."""
  from ..module import get_file_rag
  return get_file_rag()

async def add_document_endpoint(request: Dict[str, Any]):
  """Afegir document al RAG."""
  from ..module import RAGModule
  from memory.rag_sources.base import AddDocumentRequest

  try:
    module = RAGModule.get_instance()
    if not module._initialized:
      await module.initialize()

    add_request = AddDocumentRequest(
      text=request.get("text", ""),
      metadata=request.get("metadata", {}),
      chunk_size=request.get("chunk_size", 800),
      chunk_overlap=request.get("chunk_overlap", 100)
    )

    source = request.get("source", "personality")
    doc_id = await module.add_document(add_request, source=source)

    return JSONResponse(content={
      "success": True,
      "doc_id": doc_id,
      "message": _t("rag.api.document_added", "Document added successfully"),
      "source": source
    })

  except Exception as e:
    logger.error(_t(
      "rag.logs.add_document_error",
      "Error adding document via API: {error}",
      error=str(e)
    ), exc_info=True)
    raise HTTPException(status_code=500, detail=str(e))

async def search_endpoint(request: Dict[str, Any]):
  """Cercar documents rellevants."""
  from ..module import RAGModule
  from memory.rag_sources.base import SearchRequest

  start_time = time.time()

  try:
    module = RAGModule.get_instance()
    if not module._initialized:
      await module.initialize()

    search_request = SearchRequest(
      query=request.get("query", ""),
      top_k=request.get("top_k", 5),
      filters=request.get("filters", {})
    )

    source = request.get("source", "personality")
    results = await module.search(search_request, source=source)

    results_dict = [
      {
        "doc_id": r.doc_id,
        "chunk_id": r.chunk_id,
        "score": r.score,
        "text": r.text,
        "metadata": r.metadata
      }
      for r in results
    ]

    searches, duration = _get_metrics()
    if searches:
      searches.labels(source=source).inc()
    if duration:
      duration.labels(source=source).observe(time.time() - start_time)

    return JSONResponse(content={
      "success": True,
      "results": results_dict,
      "count": len(results_dict),
      "source": source
    })

  except Exception as e:
    logger.error(_t(
      "rag.logs.search_error",
      "Error searching via API: {error}",
      error=str(e)
    ), exc_info=True)
    raise HTTPException(status_code=500, detail=str(e))

async def upload_file_endpoint(file: UploadFile = File(...), metadata: str = "{}"):
  """Pujar fitxer al RAG amb auto-detecció de format."""
  try:
    try:
      meta_dict = json.loads(metadata)
    except Exception:
      meta_dict = {}

    meta_dict["filename"] = file.filename
    meta_dict["content_type"] = file.content_type

    file_path = Path(file.filename)
    ext = file_path.suffix.lower()

    if not ext:
      raise HTTPException(
        status_code=400,
        detail=_t("rag.api.file_no_extension", "File has no extension. Cannot detect format.")
      )

    MAX_FILE_SIZE_MB = 50
    MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024

    file_size = 0
    if hasattr(file, 'size') and file.size:
      file_size = file.size
    elif hasattr(file, 'file'):
      file.file.seek(0, 2)
      file_size = file.file.tell()
      file.file.seek(0)

    if file_size > MAX_FILE_SIZE_BYTES:
      raise HTTPException(
        status_code=413,
        detail=_t(
          "rag.api.file_too_large",
          "File too large ({size_mb:.1f}MB). Maximum: {max_mb}MB",
          size_mb=(file_size / 1024 / 1024),
          max_mb=MAX_FILE_SIZE_MB,
        )
      )

    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp_file:
      content = await file.read()
      tmp_file.write(content)
      tmp_path = Path(tmp_file.name)

    try:
      file_rag = _get_file_rag()
      doc_id = await file_rag.add_file(file_path=tmp_path, metadata=meta_dict)
      metrics = file_rag.get_metrics()

      return JSONResponse(content={
        "success": True,
        "doc_id": doc_id,
        "filename": file.filename,
        "format": ext,
        "chunks": metrics.get("total_chunks", 0),
        "message": _t("rag.api.file_uploaded", "File uploaded and indexed successfully"),
        "metrics": metrics
      })

    finally:
      if tmp_path.exists():
        tmp_path.unlink()

  except HTTPException:
    raise
  except Exception as e:
    logger.error(_t(
      "rag.logs.upload_error",
      "Error uploading file via API: {error}",
      error=str(e)
    ), exc_info=True)
    raise HTTPException(
      status_code=500,
      detail=_t("rag.api.file_processing_error", "Error processing file: {error}", error=str(e))
    )

async def health_endpoint():
  """Health check del mòdul RAG."""
  from ..module import RAGModule

  try:
    module = RAGModule.get_instance()
    health = module.get_health()
    status_code = 200 if health["status"] == "healthy" else 503
    return JSONResponse(content=health, status_code=status_code)

  except Exception as e:
    logger.error(_t(
      "rag.logs.health_error",
      "Error checking health via API: {error}",
      error=str(e)
    ), exc_info=True)
    return JSONResponse(content={"status": "error", "error": str(e)}, status_code=500)

async def info_endpoint():
  """Informació del mòdul RAG."""
  from ..module import RAGModule

  try:
    module = RAGModule.get_instance()
    return JSONResponse(content=module.get_info())

  except Exception as e:
    logger.error(_t(
      "rag.logs.info_error",
      "Error getting info via API: {error}",
      error=str(e)
    ), exc_info=True)
    raise HTTPException(status_code=500, detail=str(e))

async def files_stats_endpoint():
  """Obtenir estadístiques dels fitxers pujats."""
  try:
    file_rag = _get_file_rag()
    metrics = file_rag.get_metrics()

    documents = []
    if hasattr(file_rag, '_documents'):
      for doc_id, doc_info in file_rag._documents.items():
        documents.append({
          "doc_id": doc_id,
          "filename": doc_info.get("filename", _t("rag.api.unknown", "Unknown")),
          "format": doc_info.get("format", _t("rag.api.unknown", "Unknown")),
          "chunks": doc_info.get("chunks", 0),
          "uploaded_at": doc_info.get("uploaded_at", None)
        })

    return JSONResponse(content={
      "total_documents": metrics.get("total_documents", 0),
      "total_chunks": metrics.get("total_chunks", 0),
      "total_vectors": metrics.get("total_vectors", 0),
      "documents": documents
    })

  except Exception as e:
    logger.error(_t(
      "rag.logs.file_stats_error",
      "Error getting file stats via API: {error}",
      error=str(e)
    ), exc_info=True)
    raise HTTPException(status_code=500, detail=str(e))

__all__ = [
  "add_document_endpoint",
  "search_endpoint",
  "upload_file_endpoint",
  "health_endpoint",
  "info_endpoint",
  "files_stats_endpoint",
]
