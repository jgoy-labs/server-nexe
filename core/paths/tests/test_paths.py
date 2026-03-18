"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy
Location: core/paths/tests/test_paths.py
Description: Tests per core/paths (detection, helpers, validation).

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import os
import pytest
from pathlib import Path
from unittest.mock import patch

from core.paths.detection import (
    get_repo_root,
    reset_repo_root_cache,
    DetectionMethod,
    REQUIRED_MARKERS,
    OPTIONAL_MARKERS,
    NEXE_CORE_DIRS,
)
from core.paths.validation import (
    _is_valid_core_root,
    _log_detection_success,
    _log_detection_failure,
    _track_cwd_fallback_usage,
)
from core.paths.helpers import (
    get_project_path,
    get_plugins_path,
    get_memory_path,
    get_core_path,
    get_personality_path,
    get_storage_path,
    get_logs_dir,
    get_config_dir,
    get_data_dir,
    get_cache_dir,
)
import core.paths as paths_module


# ─── Tests validation.py ──────────────────────────────────────────────────────

class TestIsValidCoreRoot:

    def test_nonexistent_path_returns_false(self, tmp_path):
        fake = tmp_path / "nonexistent"
        valid, reasons = _is_valid_core_root(fake)
        assert valid is False
        assert any("does not exist" in r for r in reasons)

    def test_file_not_directory_returns_false(self, tmp_path):
        f = tmp_path / "file.txt"
        f.write_text("content")
        valid, reasons = _is_valid_core_root(f)
        assert valid is False
        assert any("not a directory" in r for r in reasons)

    def test_missing_server_toml_returns_false(self, tmp_path):
        # Crear estructura sense server.toml
        (tmp_path / "plugins").mkdir()
        (tmp_path / "core").mkdir()
        valid, reasons = _is_valid_core_root(tmp_path)
        assert valid is False
        assert any("server.toml" in r or "Required config" in r for r in reasons)

    def test_incomplete_structure_returns_false(self, tmp_path):
        # server.toml present però menys de 2 dirs
        (tmp_path / "personality").mkdir()
        (tmp_path / "personality" / "server.toml").write_text("title = 'Nexe'")
        (tmp_path / "plugins").mkdir()  # só 1 dir de 4
        valid, reasons = _is_valid_core_root(tmp_path)
        assert valid is False

    def test_valid_root(self, tmp_path):
        # Crear estructura vàlida
        (tmp_path / "personality").mkdir()
        (tmp_path / "personality" / "server.toml").write_text("title = 'Nexe'")
        (tmp_path / "plugins").mkdir()
        (tmp_path / "core").mkdir()
        (tmp_path / "memory").mkdir()
        valid, reasons = _is_valid_core_root(tmp_path)
        assert valid is True
        assert any("[OK]" in r for r in reasons)

    def test_returns_reasons_list(self, tmp_path):
        valid, reasons = _is_valid_core_root(tmp_path / "nonexistent")
        assert isinstance(reasons, list)
        assert len(reasons) > 0


class TestLogDetectionSuccess:

    def test_logs_without_crash(self, tmp_path):
        _log_detection_success(
            method=DetectionMethod.ENV_VAR,
            path=tmp_path,
            reasons=["[OK] Found"],
            warning=False
        )

    def test_logs_with_warning(self, tmp_path):
        _log_detection_success(
            method=DetectionMethod.FALLBACK_CWD,
            path=tmp_path,
            reasons=["[WARN] Using fallback"],
            warning=True
        )


class TestLogDetectionFailure:

    def test_logs_without_crash(self, tmp_path):
        _log_detection_failure(
            method=DetectionMethod.ENV_VAR,
            path=tmp_path,
            reasons=["[ERROR] Not found"]
        )


class TestTrackCwdFallback:

    def test_does_not_crash(self):
        _track_cwd_fallback_usage()


# ─── Tests detection.py ───────────────────────────────────────────────────────

class TestDetectionMethod:

    def test_has_env_var(self):
        assert DetectionMethod.ENV_VAR

    def test_has_marker_file(self):
        assert DetectionMethod.MARKER_FILE

    def test_has_start_path(self):
        assert DetectionMethod.START_PATH


class TestGetRepoRoot:

    def setup_method(self):
        reset_repo_root_cache()

    def teardown_method(self):
        # Neteja env vars temporals
        os.environ.pop("NEXE_HOME", None)
        reset_repo_root_cache()

    def test_returns_path(self):
        """Detecta la root del projecte (ha de funcionar en dev)."""
        root = get_repo_root()
        assert isinstance(root, Path)
        assert root.exists()

    def test_returns_valid_nexe_root(self):
        root = get_repo_root()
        assert (root / "personality" / "server.toml").exists()

    def test_nexe_home_env_var_used(self, tmp_path):
        """NEXE_HOME hauria de tenir prioritat màxima."""
        # Crear estructura vàlida al tmp_path
        (tmp_path / "personality").mkdir()
        (tmp_path / "personality" / "server.toml").write_text("title = 'Test'")
        (tmp_path / "plugins").mkdir()
        (tmp_path / "core").mkdir()
        (tmp_path / "memory").mkdir()

        os.environ["NEXE_HOME"] = str(tmp_path)
        reset_repo_root_cache()
        root = get_repo_root()
        assert root == tmp_path.resolve()

    def test_nexe_home_invalid_raises(self, tmp_path):
        """NEXE_HOME invàlid ha de llançar RuntimeError."""
        os.environ["NEXE_HOME"] = str(tmp_path / "nonexistent")
        reset_repo_root_cache()
        with pytest.raises(RuntimeError, match="NEXE_HOME"):
            get_repo_root()

    def test_start_path_used(self, tmp_path):
        """start_path hauria d'usar-se si és vàlid."""
        # Crear estructura vàlida
        (tmp_path / "personality").mkdir()
        (tmp_path / "personality" / "server.toml").write_text("title = 'Test'")
        (tmp_path / "plugins").mkdir()
        (tmp_path / "core").mkdir()
        (tmp_path / "memory").mkdir()

        root = get_repo_root(start_path=tmp_path)
        assert root == tmp_path.resolve()

    def test_reset_cache_works(self):
        """reset_repo_root_cache() ha de permetre re-detecció."""
        root1 = get_repo_root()
        reset_repo_root_cache()
        root2 = get_repo_root()
        assert root1 == root2  # Mateixa root


class TestConstants:

    def test_required_markers_non_empty(self):
        assert len(REQUIRED_MARKERS) > 0

    def test_optional_markers_non_empty(self):
        assert len(OPTIONAL_MARKERS) > 0

    def test_nexe_core_dirs_has_plugins(self):
        assert "plugins" in NEXE_CORE_DIRS

    def test_nexe_core_dirs_has_core(self):
        assert "core" in NEXE_CORE_DIRS


# ─── Tests helpers.py ─────────────────────────────────────────────────────────

class TestPathHelpers:

    def test_get_project_path_returns_path(self):
        p = get_project_path()
        assert isinstance(p, Path)

    def test_get_project_path_with_parts(self):
        p = get_project_path("plugins", "security")
        assert str(p).endswith("plugins/security")

    def test_get_plugins_path(self):
        p = get_plugins_path()
        assert "plugins" in str(p)

    def test_get_plugins_path_with_subdir(self):
        p = get_plugins_path("security")
        assert "plugins" in str(p)
        assert "security" in str(p)

    def test_get_memory_path(self):
        p = get_memory_path()
        assert "memory" in str(p)

    def test_get_core_path(self):
        p = get_core_path()
        assert "core" in str(p)

    def test_get_personality_path(self):
        p = get_personality_path()
        assert "personality" in str(p)

    def test_get_storage_path(self):
        p = get_storage_path()
        assert "storage" in str(p)

    def test_get_logs_dir_returns_path(self, tmp_path):
        with patch.dict(os.environ, {"NEXE_LOGS_DIR": str(tmp_path / "logs")}):
            p = get_logs_dir()
        assert isinstance(p, Path)

    def test_get_logs_dir_with_env(self, tmp_path):
        logs = tmp_path / "custom_logs"
        with patch.dict(os.environ, {"NEXE_LOGS_DIR": str(logs)}):
            p = get_logs_dir()
        assert p == logs
        assert logs.exists()

    def test_get_logs_dir_default(self):
        p = get_logs_dir()
        assert isinstance(p, Path)
        assert p.exists()

    def test_get_config_dir(self):
        p = get_config_dir()
        assert "personality" in str(p)

    def test_get_data_dir(self):
        p = get_data_dir()
        assert isinstance(p, Path)
        assert p.exists()

    def test_get_data_dir_with_subdir(self, tmp_path):
        p = get_data_dir("test_subdir")
        assert "test_subdir" in str(p)

    def test_get_cache_dir(self):
        p = get_cache_dir()
        assert isinstance(p, Path)

    def test_get_cache_dir_with_subdir(self):
        p = get_cache_dir("test_cache")
        assert "test_cache" in str(p)


# ─── Tests __init__.py (façade) ───────────────────────────────────────────────

class TestPathsFacade:

    def test_get_repo_root_available(self):
        from core.paths import get_repo_root
        assert callable(get_repo_root)

    def test_get_project_path_available(self):
        from core.paths import get_project_path
        assert callable(get_project_path)

    def test_get_plugins_path_available(self):
        from core.paths import get_plugins_path
        assert callable(get_plugins_path)

    def test_detection_method_available(self):
        from core.paths import DetectionMethod
        assert DetectionMethod.ENV_VAR

    def test_module_version(self):
        from core.paths import __version__
        assert __version__ == "2.0.0"
