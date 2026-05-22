"""
F5.4 Bug G — regression tests: MemoryService (lifespan_modules) must use the
canonical sidecar vectors_dir when running in sidecar mode, so MemoryService
and MemoryAPI share the SAME qdrant collection on disk.

Empirical evidence: the G10 sidecar log shows TWO qdrant paths:
    MemoryAPI created (qdrant_path=/Users/nexe/.../sidecar/vectors, ...)
    MemoryService initialized (db=/Users/nexe/.../sidecar/app/storage/vectors/memory_v1.db)

The first is data_dir/vectors (sidecar_config.py:169 — vectors_fallback for
sidecar mode). The second is hardcoded `project_root / "storage" / "vectors"`
in core/lifespan_modules.py:314 — which resolves to /sidecar/app/storage/
vectors (NOT data_dir/vectors).

Consequence: two qdrant collections, one for each consumer. DreamingCycle
writes to one, RAG reads from another. Semantic search silently returns 0.

Fix expected: lifespan_modules.py uses get_sidecar_config().vectors_dir
(when available) so both consumers share the same qdrant path.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ──────────────────────────────────────────────────────────────────────────────
# Bug G: lifespan_modules MemoryService must use canonical vectors_dir
# ──────────────────────────────────────────────────────────────────────────────


class TestMemoryServiceUsesCanonicalQdrantPath:

    @pytest.mark.asyncio
    async def test_sidecar_mode_memory_service_uses_vectors_dir_not_storage_vectors(
        self, tmp_path
    ):
        """In sidecar mode, MemoryService must use sidecar_config.vectors_dir
        (data_dir/vectors), NOT the hardcoded project_root/storage/vectors,
        so MemoryAPI and MemoryService share the same Qdrant collection."""
        from core.lifespan_modules import start_memory_service_v1

        # Build minimal app + server_state mocks
        class _State:
            pass

        app = _State()
        app.state = _State()
        app.state.memory_service = None

        server_state = _State()
        server_state.project_root = str(tmp_path / "project")
        Path(server_state.project_root).mkdir(parents=True, exist_ok=True)

        # Build a mock SidecarConfig with explicit vectors_dir
        canonical_vectors_dir = tmp_path / "data" / "vectors"
        canonical_vectors_dir.mkdir(parents=True, exist_ok=True)

        # Sentinel value to detect which qdrant_path is passed to MemoryService.
        captured_qdrant_path: list[str] = []

        def _capture_memory_service(db_path, qdrant_path, **kwargs):
            captured_qdrant_path.append(str(qdrant_path))
            ms = MagicMock()
            ms.initialize = MagicMock(return_value=None)
            # Make it awaitable
            async def _init():
                return None
            ms.initialize = _init
            ms._store = MagicMock()
            ms._vector_index = MagicMock()
            return ms

        # Patch get_memory_service to return None (forces fallback path)
        # and patch MemoryService to capture the qdrant_path arg.
        with patch(
            "memory.memory.module.get_memory_service",
            return_value=None,
        ), patch(
            "memory.memory.memory_service.MemoryService",
            side_effect=_capture_memory_service,
        ), patch(
            "core.sidecar_config.get_sidecar_config"
        ) as mock_get_cfg:
            mock_cfg = MagicMock()
            mock_cfg.vectors_dir = canonical_vectors_dir
            mock_cfg.is_sidecar = True
            mock_get_cfg.return_value = mock_cfg

            await start_memory_service_v1(app, server_state)

        # The captured qdrant_path must be the canonical vectors_dir from
        # sidecar_config, NOT the hardcoded project_root/storage/vectors.
        assert captured_qdrant_path, (
            "MemoryService was never instantiated — the test setup is wrong."
        )
        actual = captured_qdrant_path[0]
        expected_canonical = str(canonical_vectors_dir)
        wrong_hardcoded = str(Path(server_state.project_root) / "storage" / "vectors")

        assert actual == expected_canonical, (
            f"Bug G: MemoryService used qdrant_path={actual!r} instead of the "
            f"canonical sidecar vectors_dir={expected_canonical!r}. "
            f"This is the path mismatch that splits qdrant collections between "
            f"MemoryService and MemoryAPI.\n"
            f"  (the buggy hardcoded path was: {wrong_hardcoded!r})"
        )
