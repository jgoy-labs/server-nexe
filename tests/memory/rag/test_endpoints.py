"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: memory/rag/tests/test_endpoints.py
Description: Unit tests for RAG endpoints (upload, search, add_document).

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import io
import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException
from fastapi.responses import JSONResponse


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════

def _make_upload_file(filename: str, content: bytes = b"hello world", content_type: str = "text/plain"):
    """Creates a mock UploadFile for tests."""
    mock_file = MagicMock()
    mock_file.filename = filename
    mock_file.content_type = content_type
    mock_file.size = len(content)
    mock_file.read = AsyncMock(return_value=content)
    mock_file.file = io.BytesIO(content)
    return mock_file


# ═══════════════════════════════════════════════════════════════════════════
# Upload endpoint
# ═══════════════════════════════════════════════════════════════════════════
