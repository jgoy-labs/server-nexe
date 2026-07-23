"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: memory/rag/tests/test_routers.py
Description: Tests per memory/rag/routers/endpoints.py i ui.py.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ─── TestRagEndpoints ─────────────────────────────────────────────────────────

class TestHealthEndpoint:

    def test_healthy(self):
        from memory.rag.routers.endpoints import health_endpoint

        mock_module = MagicMock()
        mock_module._initialized = True
        mock_module.get_health = AsyncMock(return_value={"status": "HEALTHY"})

        with patch("memory.rag.module.RAGModule") as mock_cls:
            mock_cls.get_instance.return_value = mock_module
            result = asyncio.run(health_endpoint())

        data = json.loads(result.body)
        assert "status" in data

    def test_returns_unhealthy_on_error(self):
        from memory.rag.routers.endpoints import health_endpoint

        with patch("memory.rag.module.RAGModule") as mock_cls:
            mock_cls.get_instance.side_effect = Exception("Module not found")
            result = asyncio.run(health_endpoint())

        data = json.loads(result.body)
        assert data.get("status") in ("UNHEALTHY", "ERROR") or "error" in data


class TestInfoEndpoint:

    def test_info_returns_data(self):
        from memory.rag.routers.endpoints import info_endpoint

        mock_module = MagicMock()
        mock_module._initialized = True
        mock_module.get_info = MagicMock(return_value={"name": "rag"})

        with patch("memory.rag.module.RAGModule") as mock_cls:
            mock_cls.get_instance.return_value = mock_module
            result = asyncio.run(info_endpoint())

        data = json.loads(result.body)
        assert isinstance(data, dict)

