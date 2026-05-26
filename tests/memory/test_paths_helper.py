"""F2.2: tests for memory.memory._paths.resolve_qdrant_path helper.

Validates that the helper resolves to SidecarConfig.vectors_dir in sidecar
mode and falls back to the legacy literal "storage/vectors" in standalone
(or when SidecarConfig is unavailable).
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from memory.memory._paths import _LEGACY_DEFAULT, resolve_qdrant_path


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
    assert any("F2.2" in rec.message for rec in caplog.records)


def test_legacy_default_value():
    """Sanity check: legacy default remains 'storage/vectors' for backward compat."""
    assert _LEGACY_DEFAULT == Path("storage/vectors")
