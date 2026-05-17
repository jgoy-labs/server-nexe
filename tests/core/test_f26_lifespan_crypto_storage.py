"""F2.6 — lifespan_crypto storage root honours sidecar mode.

Verifies that `_resolve_storage_root` returns `SidecarConfig.data_dir` when
the process runs as a Tauri sidecar (NEXE_SIDECAR=1) and falls back to the
legacy `project_root/storage` layout otherwise.
"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from core.lifespan_crypto import _resolve_storage_root


def _make_state(project_root: Path | None):
  """Build a minimal server_state stub exposing only project_root."""
  return SimpleNamespace(project_root=project_root)


def test_sidecar_mode_returns_data_dir(tmp_path):
  """In sidecar mode, storage root must come from SidecarConfig.data_dir."""
  data_dir = tmp_path / "sidecar-data"
  data_dir.mkdir()

  fake_cfg = SimpleNamespace(is_sidecar=True, data_dir=data_dir)

  with patch("core.sidecar_config.get_sidecar_config", return_value=fake_cfg):
    result = _resolve_storage_root(_make_state(Path("/should/be/ignored")))

  assert result == data_dir


def test_standalone_mode_falls_back_to_project_root(tmp_path):
  """Without sidecar flag, return project_root/storage as before."""
  project_root = tmp_path / "repo"
  project_root.mkdir()

  fake_cfg = SimpleNamespace(is_sidecar=False, data_dir=tmp_path / "unused")

  with patch("core.sidecar_config.get_sidecar_config", return_value=fake_cfg):
    result = _resolve_storage_root(_make_state(project_root))

  assert result == project_root / "storage"


def test_sidecar_config_unavailable_falls_back(tmp_path):
  """If SidecarConfig blows up, log and return project_root/storage."""
  project_root = tmp_path / "repo"

  with patch("core.sidecar_config.get_sidecar_config", side_effect=RuntimeError("boom")):
    result = _resolve_storage_root(_make_state(project_root))

  assert result == project_root / "storage"


def test_no_project_root_returns_none():
  """Defensive: with no project_root and not sidecar, return None."""
  fake_cfg = SimpleNamespace(is_sidecar=False, data_dir=Path("/unused"))

  with patch("core.sidecar_config.get_sidecar_config", return_value=fake_cfg):
    result = _resolve_storage_root(_make_state(None))

  assert result is None
