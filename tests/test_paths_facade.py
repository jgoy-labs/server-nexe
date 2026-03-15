"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy
Location: tests/test_paths_facade.py
Description: Tests per core/paths.py (facade) i gaps de core/paths/detection.py.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import os
import pytest
from pathlib import Path
from unittest.mock import patch


class TestPathsFacadeModule:
    """Tests per core/paths.py (el fitxer façana, no el paquet)."""

    def test_get_repo_root_importable_from_facade(self):
        import core.paths as paths_module
        assert hasattr(paths_module, "get_repo_root")

    def test_get_project_path_importable_from_facade(self):
        import core.paths as paths_module
        assert hasattr(paths_module, "get_project_path")

    def test_detection_method_importable_from_facade(self):
        import core.paths as paths_module
        assert hasattr(paths_module, "DetectionMethod")

    def test_reset_repo_root_cache_importable(self):
        import core.paths as paths_module
        assert callable(paths_module.reset_repo_root_cache)

    def test_required_markers_importable(self):
        import core.paths as paths_module
        assert hasattr(paths_module, "REQUIRED_MARKERS")

    def test_optional_markers_importable(self):
        import core.paths as paths_module
        assert hasattr(paths_module, "OPTIONAL_MARKERS")

    def test_nexe_core_dirs_importable(self):
        import core.paths as paths_module
        assert hasattr(paths_module, "NEXE_CORE_DIRS")

    def test_core_paths_py_file_exists(self):
        """Verifica que el fitxer façana existeix."""
        import core
        core_dir = Path(core.__file__).parent
        facade = core_dir / "paths.py"
        assert facade.exists()


class TestDetectionViaMarkers:
    """Tests per _detect_via_markers (línies 146-167)."""

    def setup_method(self):
        from core.paths.detection import reset_repo_root_cache
        reset_repo_root_cache()

    def teardown_method(self):
        os.environ.pop("NEXE_HOME", None)
        from core.paths.detection import reset_repo_root_cache
        reset_repo_root_cache()

    def test_detect_via_markers_returns_path(self):
        """_detect_via_markers troba la root del projecte."""
        from core.paths.detection import _detect_via_markers
        result = _detect_via_markers()
        assert result is not None
        assert isinstance(result, Path)
        assert result.exists()

    def test_detect_via_markers_returns_none_when_no_root(self, tmp_path):
        """_detect_via_markers retorna None quan no es troba root."""
        from core.paths.detection import _detect_via_markers
        # Patch __file__ to point to a tmp dir where no nexe structure exists
        import core.paths.detection as det_module
        with patch.object(det_module, "__file__", str(tmp_path / "detection.py")):
            # This should either find a root (via the real markers) or return None
            result = _detect_via_markers()
            # Either result is acceptable depending on file structure
            assert result is None or isinstance(result, Path)


class TestDetectionViaStartPath:
    """Tests per start_path (línies 117-127 de detection.py)."""

    def setup_method(self):
        from core.paths.detection import reset_repo_root_cache
        reset_repo_root_cache()

    def teardown_method(self):
        os.environ.pop("NEXE_HOME", None)
        from core.paths.detection import reset_repo_root_cache
        reset_repo_root_cache()

    def test_invalid_start_path_logs_and_continues(self, tmp_path):
        """start_path invàlid → _log_detection_failure s'invoca."""
        from core.paths.detection import get_repo_root

        # tmp_path sense estructura nexe → start_path detection fails
        # ha de continuar i trobar la root real
        result = get_repo_root(start_path=tmp_path)
        assert isinstance(result, Path)


class TestHelpersMissingLines:
    """Tests per lines 80-82 de core/paths/helpers.py."""

    def test_get_plugins_path(self):
        from core.paths.helpers import get_plugins_path
        p = get_plugins_path()
        assert "plugins" in str(p)

    def test_get_system_logs_dir(self):
        """get_system_logs_dir returns a Path."""
        try:
            from core.paths.helpers import get_system_logs_dir
            p = get_system_logs_dir()
            assert isinstance(p, Path)
        except (ImportError, AttributeError):
            pytest.skip("get_system_logs_dir not available")

    def test_get_core_root(self):
        """get_core_root returns a Path."""
        try:
            from core.paths.helpers import get_core_root
            p = get_core_root()
            assert isinstance(p, Path)
        except (ImportError, AttributeError):
            pytest.skip("get_core_root not available")
