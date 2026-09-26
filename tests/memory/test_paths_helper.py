"""F2.2: tests for memory.memory._paths.resolve_qdrant_path helper.

Validates that the helper resolves to SidecarConfig.vectors_dir in sidecar
mode and falls back to the legacy literal "storage/vectors" in standalone
(or when SidecarConfig is unavailable).
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from memory.memory._paths import _LEGACY_DEFAULT, resolve_qdrant_path


@pytest.fixture(autouse=True)
def _no_qdrant_path_env(monkeypatch):
    """The cases below are about the defaults: the variable must not be set."""
    monkeypatch.delenv("NEXE_QDRANT_PATH", raising=False)


def test_returns_legacy_default_when_standalone(monkeypatch, caplog):
    """Standalone mode (is_sidecar=False) → returns the legacy default literal."""
    fake_cfg = MagicMock(is_sidecar=False, vectors_dir=Path("/should/not/be/used"))
    with patch("core.sidecar_config.get_sidecar_config", return_value=fake_cfg):
        result = resolve_qdrant_path()
    assert result == _LEGACY_DEFAULT


def test_returns_sidecar_vectors_dir_when_sidecar():
    """Sidecar mode → returns SidecarConfig.vectors_dir."""
    expected = Path("/Users/testuser/.nexe/data/vectors")
    fake_cfg = MagicMock(is_sidecar=True, vectors_dir=expected)
    with patch("core.sidecar_config.get_sidecar_config", return_value=fake_cfg):
        result = resolve_qdrant_path()
    assert result == expected


def test_custom_default_used_when_standalone():
    """Standalone with custom default → returns the custom default."""
    custom = Path("/tmp/custom/vectors")
    fake_cfg = MagicMock(is_sidecar=False, vectors_dir=Path("/ignored"))
    with patch("core.sidecar_config.get_sidecar_config", return_value=fake_cfg):
        result = resolve_qdrant_path(custom)
    assert result == custom


def test_string_default_converted_to_path():
    """String default in standalone → returns Path equivalent."""
    fake_cfg = MagicMock(is_sidecar=False, vectors_dir=Path("/ignored"))
    with patch("core.sidecar_config.get_sidecar_config", return_value=fake_cfg):
        result = resolve_qdrant_path("relative/path/vectors")
    assert result == Path("relative/path/vectors")


def test_fallback_when_sidecar_config_raises(caplog):
    """Exception in SidecarConfig → fallback to default + log debug."""
    with patch(
        "core.sidecar_config.get_sidecar_config",
        side_effect=RuntimeError("config unavailable"),
    ):
        with caplog.at_level("DEBUG"):
            result = resolve_qdrant_path()
    assert result == _LEGACY_DEFAULT
    assert any("SidecarConfig unavailable" in rec.message for rec in caplog.records)


def test_legacy_default_value():
    """Sanity check: legacy default remains 'storage/vectors' for backward compat."""
    assert _LEGACY_DEFAULT == Path("storage/vectors")


def test_standalone_honours_nexe_qdrant_path(monkeypatch, tmp_path):
    """#1053: the core's Qdrant followed NEXE_QDRANT_PATH and memory did not —
    a live run isolated by the variable still wrote facts into the DEV store
    (seen 25/09). Standalone now resolves it too."""
    monkeypatch.setenv("NEXE_QDRANT_PATH", str(tmp_path / "vectors"))
    fake_cfg = MagicMock(is_sidecar=False, vectors_dir=Path("/ignored"))
    with patch("core.sidecar_config.get_sidecar_config", return_value=fake_cfg):
        assert resolve_qdrant_path() == tmp_path / "vectors"
        assert resolve_qdrant_path(Path("/some/default")) == tmp_path / "vectors"


def test_relative_nexe_qdrant_path_is_anchored_where_the_core_anchors_it(monkeypatch):
    """A relative value lands where core.qdrant_pool opens it, not under the cwd."""
    from core.qdrant_pool import _anchor_path

    monkeypatch.setenv("NEXE_QDRANT_PATH", "storage/vectors")
    fake_cfg = MagicMock(is_sidecar=False, vectors_dir=Path("/ignored"))
    with patch("core.sidecar_config.get_sidecar_config", return_value=fake_cfg):
        result = resolve_qdrant_path()
    assert result.is_absolute()
    assert result == _anchor_path("storage/vectors")


def test_relative_nexe_qdrant_path_is_anchored_at_the_callers_root(monkeypatch, tmp_path):
    """A unit test's tmp project_root must never land on the repo's store: the
    DEV .env's `storage/vectors` is loaded into every process by runner.py."""
    monkeypatch.setenv("NEXE_QDRANT_PATH", "storage/vectors")
    fake_cfg = MagicMock(is_sidecar=False, vectors_dir=Path("/ignored"))
    with patch("core.sidecar_config.get_sidecar_config", return_value=fake_cfg):
        assert resolve_qdrant_path(Path("/x/default"), root=tmp_path) == tmp_path / "storage/vectors"


def test_relative_nexe_qdrant_path_keeps_a_callers_own_default(monkeypatch):
    """No root but a default: the caller looks at its own storage dir, as before #1053."""
    monkeypatch.setenv("NEXE_QDRANT_PATH", "storage/vectors")
    fake_cfg = MagicMock(is_sidecar=False, vectors_dir=Path("/ignored"))
    with patch("core.sidecar_config.get_sidecar_config", return_value=fake_cfg):
        assert resolve_qdrant_path(Path("/elsewhere/vectors")) == Path("/elsewhere/vectors")
