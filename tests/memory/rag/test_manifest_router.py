"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: memory/rag/tests/test_manifest_router.py
Description: Tests per memory/rag/manifest.py i memory/rag/router.py.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestRagManifest:

    def test_get_router_returns_router(self):
        from memory.rag.manifest import get_router
        router = get_router()
        assert router is not None

    def test_get_metadata_returns_dict(self):
        from memory.rag.manifest import get_metadata
        meta = get_metadata()
        assert isinstance(meta, dict)
        assert "name" in meta

    def test_getattr_router_public(self):
        import memory.rag.manifest as m
        router = m.router_public
        assert router is not None

    def test_getattr_unknown_raises(self):
        import memory.rag.manifest as m
        with pytest.raises(AttributeError):
            _ = m.nonexistent_attribute


class TestRagRouter:

    def test_get_router(self):
        from memory.rag.router import get_router, router_public
        assert get_router() is router_public

    def test_get_metadata(self):
        from memory.rag.router import get_metadata, MODULE_METADATA
        assert get_metadata() is MODULE_METADATA

    def test_metadata_has_rag_name(self):
        from memory.rag.router import MODULE_METADATA
        assert MODULE_METADATA["name"] == "rag"
