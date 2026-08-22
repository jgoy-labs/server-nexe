"""
Additional coverage tests for memory/rag/health.py
Covers: check_qdrant_available exception branches, check_storage_paths not writable,
        check_rag_sources source health exception, check_health exception path,
        check_disk_space warn/degrade (never fail-by-value)
"""

import pytest
from unittest.mock import MagicMock, patch, PropertyMock

from memory.rag.health import (
    check_qdrant_available,
    check_storage_paths,
    check_rag_sources,
    check_health,
    check_disk_space,
)


class TestCheckQdrantAvailableCoverage:
    """Gate G8 (#891): the check must reflect whether the store ANSWERS.

    The two tests that lived here documented the bug instead of catching it.
    One patched importlib.metadata to fail and then asserted status == "pass"
    — writing down that the check reports Qdrant available while knowing
    nothing about it. The other asserted `status in ["pass", "fail"]`, which
    cannot fail. Between them, the check could never go red, and everything
    downstream (readiness, /status, the watcher's eye) inherited that.
    """

    def test_a_store_that_does_not_answer_reports_fail(self):
        """G8: kill Qdrant -> the check says fail. This is the whole point."""
        with patch("core.qdrant_pool.qdrant_status",
                   return_value=(False, "ResponseHandlingException: Connection refused")):
            result = check_qdrant_available()
        assert result["status"] == "fail", (
            "the store is not answering and the check still reports pass — "
            "this is #891, and it leaves the quarantine mechanism with no input"
        )
        assert "Connection refused" in result["message"], "the reason has to reach the reader"

    def test_a_responding_store_reports_pass(self):
        """Control: without this, a check hardwired to 'fail' would pass above."""
        with patch("core.qdrant_pool.qdrant_status", return_value=(True, "6 collection(s)")):
            result = check_qdrant_available()
        assert result["status"] == "pass"
        assert result["name"] == "qdrant_available"

    def test_the_check_reads_the_observation_and_does_not_probe(self):
        """get_health() runs synchronously on the event loop and the interface
        polls readiness every 3s: probing here would stall the server for as
        long as the store takes to answer. The watcher probes; this reads."""
        with patch("core.qdrant_pool.probe_qdrant") as probe, \
             patch("core.qdrant_pool.qdrant_status", return_value=(True, "ok")):
            check_qdrant_available()
        probe.assert_not_called()

    def test_the_old_shape_would_have_missed_it(self):
        """Calibration: the version-only check answered 'pass' with the store
        unreachable. Reproduced here so the gate above is demonstrably able to
        tell the two implementations apart."""
        import importlib.metadata

        def legacy_check():
            try:
                version = importlib.metadata.version("qdrant-client")
            except Exception:
                version = "unknown"
            return {"name": "qdrant_available", "status": "pass", "message": version}

        with patch("core.qdrant_pool.qdrant_status", return_value=(False, "Connection refused")):
            assert legacy_check()["status"] == "pass", "calibration: the old shape never failed"
            assert check_qdrant_available()["status"] == "fail", "and the new one does"


class TestCheckStoragePathsCoverage:

    def test_storage_paths_not_writable(self):
        """When paths exist but are not writable."""
        with patch("memory.rag.health.Path") as MockPath:
            mock_dir = MagicMock()
            mock_dir.mkdir = MagicMock()
            mock_test_file = MagicMock()
            mock_test_file.write_text.side_effect = PermissionError("denied")
            mock_dir.__truediv__ = MagicMock(return_value=mock_test_file)
            MockPath.return_value = mock_dir
            result = check_storage_paths()
            assert result["name"] == "storage_paths"

    def test_storage_paths_exception(self):
        """When path creation raises exception."""
        with patch("core.paths.get_repo_root", side_effect=Exception("filesystem error")):
            result = check_storage_paths()
            assert result["status"] == "fail"


class TestCheckRagSourcesCoverage:

    def test_source_health_exception(self):
        """When a source's health() raises exception."""
        mock_source = MagicMock()
        mock_source.health.side_effect = Exception("health error")

        mock_module = MagicMock()
        mock_module._initialized = True
        mock_module._sources = {"broken": mock_source}

        result = check_rag_sources(mock_module)
        assert result["status"] == "fail"
        assert "broken" in result["sources"]
        assert result["sources"]["broken"]["status"] == "unhealthy"

    def test_source_degraded_status(self):
        """When a source reports degraded status."""
        mock_source = MagicMock()
        mock_source.health.return_value = {"status": "degraded"}

        mock_module = MagicMock()
        mock_module._initialized = True
        mock_module._sources = {"degraded_src": mock_source}

        result = check_rag_sources(mock_module)
        assert result["status"] == "fail"


class TestCheckDiskSpaceCoverage:

    def test_disk_space_critical(self):
        """Disk below the critical threshold degrades (warn), never fails."""
        mock_usage = MagicMock()
        mock_usage.free = 1 * 1024 ** 3  # 1 GB
        with patch("memory.rag.health.psutil") as mock_psutil:
            mock_psutil.disk_usage.return_value = mock_usage
            result = check_disk_space(min_gb=100.0)
            assert result["status"] == "warn"

    def test_disk_space_warn(self):
        """Disk space in warning range."""
        mock_usage = MagicMock()
        mock_usage.free = 7 * 1024 ** 3  # 7 GB
        with patch("memory.rag.health.psutil") as mock_psutil:
            mock_psutil.disk_usage.return_value = mock_usage
            result = check_disk_space(min_gb=10.0)
            assert result["status"] == "warn"

    def test_disk_space_never_fails_on_zero_free(self):
        """Even 0 bytes free degrades (warn) — the app must still boot."""
        mock_usage = MagicMock()
        mock_usage.free = 0
        with patch("memory.rag.health.psutil") as mock_psutil:
            mock_psutil.disk_usage.return_value = mock_usage
            result = check_disk_space(min_gb=10.0)
            assert result["status"] == "warn"

    def test_disk_space_threshold_from_env(self, monkeypatch):
        """NEXE_RAG_MIN_DISK_GB overrides the default; malformed falls back to 5 GB."""
        mock_usage = MagicMock()
        mock_usage.free = 3 * 1024 ** 3  # 3 GB free
        with patch("memory.rag.health.psutil") as mock_psutil:
            mock_psutil.disk_usage.return_value = mock_usage
            # Default 5 GB → 3 GB below → warn
            monkeypatch.delenv("NEXE_RAG_MIN_DISK_GB", raising=False)
            assert check_disk_space()["status"] == "warn"
            # Override to 2 GB → 3 GB above → pass
            monkeypatch.setenv("NEXE_RAG_MIN_DISK_GB", "2")
            assert check_disk_space()["status"] == "pass"
            # Malformed → fallback to 5 GB default → 3 GB below → warn
            monkeypatch.setenv("NEXE_RAG_MIN_DISK_GB", "not-a-number")
            assert check_disk_space()["status"] == "warn"
            # Non-positive → clamped to 5 GB default (not an always-pass no-op) → warn
            monkeypatch.setenv("NEXE_RAG_MIN_DISK_GB", "-5")
            assert check_disk_space()["status"] == "warn"


class TestCheckHealthCoverage:

    def test_check_health_degraded(self):
        """Module with warn status."""
        mock_module = MagicMock()
        mock_module._initialized = True
        mock_module._sources = {}  # Will cause rag_sources fail
        mock_module.module_id = "TEST"
        mock_module.name = "rag"
        mock_module.version = "0.1"
        mock_module._stats = {}
        # Some checks may return warn
        result = check_health(mock_module)
        assert result["status"] in ["unhealthy", "degraded"]

    def test_check_health_exception(self):
        """When check_health itself raises."""
        mock_module = MagicMock()
        type(mock_module)._initialized = PropertyMock(side_effect=Exception("boom"))

        result = check_health(mock_module)
        assert result["status"] == "unhealthy"
        assert "error" in result["metadata"]
