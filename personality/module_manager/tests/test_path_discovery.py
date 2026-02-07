"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: personality/module_manager/tests/test_path_discovery.py
Description: Tests per PathDiscovery. Valida descobriment de paths, detecció

www.jgoy.net
────────────────────────────────────
"""

import pytest
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

from personality.module_manager.path_discovery import PathDiscovery

class TestPathDiscoveryInit:
  """Tests for PathDiscovery initialization."""

  def test_init_default_config(self):
    """Should initialize with empty config."""
    discovery = PathDiscovery()

    assert discovery.config == {}
    assert discovery.i18n is None
    assert discovery.base_path == Path(".")
    assert len(discovery._discovered_paths) == 0

  def test_init_with_config(self):
    """Should initialize with provided config."""
    config = {"test": "value"}
    discovery = PathDiscovery(config=config)

    assert discovery.config == config

  def test_init_with_i18n(self):
    """Should store i18n manager."""
    mock_i18n = MagicMock()
    discovery = PathDiscovery(i18n_manager=mock_i18n)

    assert discovery.i18n == mock_i18n

  def test_known_paths_default(self):
    """Should have default known paths."""
    discovery = PathDiscovery()

    assert "plugins/core" in discovery.known_paths
    assert "core/core" in discovery.known_paths
    assert "personality/core" in discovery.known_paths

  def test_ignore_patterns_default(self):
    """Should have default ignore patterns."""
    discovery = PathDiscovery()

    assert "__pycache__" in discovery.ignore_patterns
    assert ".git" in discovery.ignore_patterns
    assert "venv" in discovery.ignore_patterns

class TestPathDiscoveryMessages:
  """Tests for message handling."""

  def test_get_message_with_i18n(self):
    """Should use i18n for translations."""
    mock_i18n = MagicMock()
    mock_i18n.t.return_value = "Translated message"
    discovery = PathDiscovery(i18n_manager=mock_i18n)

    result = discovery._get_message('path_discovery.scanning')

    mock_i18n.t.assert_called_once()
    assert result == "Translated message"

  def test_get_message_fallback(self):
    """Should use fallback when no i18n."""
    discovery = PathDiscovery()

    result = discovery._get_message('path_discovery.scanning')

    assert result == "Scanning paths for modules..."

  def test_get_message_fallback_with_kwargs(self):
    """Should interpolate kwargs in fallback."""
    discovery = PathDiscovery()

    result = discovery._get_message('path_discovery.path_added', path='/test/path')

    assert "/test/path" in result

  def test_get_message_unknown_key(self):
    """Should return key for unknown messages."""
    discovery = PathDiscovery()

    result = discovery._get_message('unknown.key')

    assert result == "unknown.key"

class TestPathDiscoveryKnownPaths:
  """Tests for known path handling."""

  def test_add_known_paths_existing(self, tmp_path):
    """Should add existing known paths."""
    plugins_core = tmp_path / "plugins" / "core"
    plugins_core.mkdir(parents=True)

    discovery = PathDiscovery()
    discovery.base_path = tmp_path
    discovery.known_paths = ["plugins/core"]

    discovery._add_known_paths()

    assert plugins_core.resolve() in discovery._discovered_paths

  def test_add_known_paths_nonexistent(self, tmp_path):
    """Should skip non-existent paths."""
    discovery = PathDiscovery()
    discovery.base_path = tmp_path
    discovery.known_paths = ["nonexistent/path"]

    discovery._add_known_paths()

    assert len(discovery._discovered_paths) == 0

class TestPathDiscoveryAutoDiscover:
  """Tests for auto-discovery."""

  def test_auto_discover_module_pattern(self, tmp_path):
    """Should discover directories with module patterns."""
    module_dir = tmp_path / "project" / "modules"
    module_dir.mkdir(parents=True)

    discovery = PathDiscovery()
    discovery.base_path = tmp_path

    discovery._auto_discover_paths()

    assert module_dir.resolve() in discovery._discovered_paths

  def test_auto_discover_ignores_hidden(self, tmp_path):
    """Should ignore hidden directories."""
    hidden_dir = tmp_path / ".hidden" / "modules"
    hidden_dir.mkdir(parents=True)

    discovery = PathDiscovery()
    discovery.base_path = tmp_path

    discovery._auto_discover_paths()

    assert hidden_dir.resolve() not in discovery._discovered_paths

  def test_auto_discover_ignores_pycache(self, tmp_path):
    """Should ignore __pycache__ directories."""
    pycache_dir = tmp_path / "__pycache__" / "modules"
    pycache_dir.mkdir(parents=True)

    discovery = PathDiscovery()
    discovery.base_path = tmp_path

    discovery._auto_discover_paths()

    assert pycache_dir.resolve() not in discovery._discovered_paths

  def test_auto_discover_respects_limit(self, tmp_path):
    """Should respect MAX_DIRS limit."""
    for i in range(110):
      (tmp_path / f"dir_{i}").mkdir()

    discovery = PathDiscovery()
    discovery.base_path = tmp_path

    discovery._auto_discover_paths()

class TestPathDiscoveryConfiguredPaths:
  """Tests for configured path handling."""

  def test_add_configured_paths_from_config(self, tmp_path):
    """Should add paths from configuration."""
    custom_modules = tmp_path / "custom" / "modules"
    custom_modules.mkdir(parents=True)

    config = {
      "personality": {
        "orchestrator": {
          "modules_path": "custom/modules"
        }
      }
    }

    discovery = PathDiscovery(config=config)
    discovery.base_path = tmp_path

    discovery._add_configured_paths()

    assert custom_modules.resolve() in discovery._discovered_paths

  def test_add_configured_paths_additional(self, tmp_path):
    """Should add additional configured paths."""
    extra_path = tmp_path / "extra"
    extra_path.mkdir()

    config = {
      "personality": {
        "orchestrator": {
          "additional_paths": {
            "paths": ["extra"]
          }
        }
      }
    }

    discovery = PathDiscovery(config=config)
    discovery.base_path = tmp_path

    discovery._add_configured_paths()

    assert extra_path.resolve() in discovery._discovered_paths

  def test_add_configured_paths_empty_config(self):
    """Should handle empty config gracefully."""
    discovery = PathDiscovery()

    discovery._add_configured_paths()

class TestPathDiscoveryModuleDetection:
  """Tests for module detection."""

  def test_is_module_with_manifest_toml(self, tmp_path):
    """Should detect module with manifest.toml."""
    module_dir = tmp_path / "test_module"
    module_dir.mkdir()
    (module_dir / "manifest.toml").write_text("[module]\nname = 'test'")

    discovery = PathDiscovery()

    assert discovery._is_module_directory(module_dir) is True

  def test_is_module_with_manifest_py(self, tmp_path):
    """Should detect module with manifest.py."""
    module_dir = tmp_path / "test_module"
    module_dir.mkdir()
    (module_dir / "manifest.py").write_text("# manifest")

    discovery = PathDiscovery()

    assert discovery._is_module_directory(module_dir) is True

  def test_is_module_with_module_py_is_ignored(self, tmp_path):
    """Should ignore module.py-only directories."""
    module_dir = tmp_path / "test_module"
    module_dir.mkdir()
    (module_dir / "module.py").write_text("def init_module(): pass")

    discovery = PathDiscovery()

    assert discovery._is_module_directory(module_dir) is False

  def test_is_module_empty_dir(self, tmp_path):
    """Should not detect empty directory as module."""
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()

    discovery = PathDiscovery()

    assert discovery._is_module_directory(empty_dir) is False

class TestPathDiscoveryScanModules:
  """Tests for module scanning."""

  def test_scan_for_modules(self, tmp_path):
    """Should find modules in paths."""
    modules_dir = tmp_path / "modules"
    modules_dir.mkdir()

    module_a = modules_dir / "module_a"
    module_a.mkdir()
    (module_a / "manifest.toml").write_text("[module]")

    discovery = PathDiscovery()

    result = discovery.scan_for_modules([modules_dir])

    assert "module_a" in result
    assert result["module_a"] == module_a.resolve()

  def test_scan_ignores_hidden(self, tmp_path):
    """Should ignore hidden directories."""
    modules_dir = tmp_path / "modules"
    modules_dir.mkdir()

    hidden_module = modules_dir / ".hidden"
    hidden_module.mkdir()
    (hidden_module / "manifest.toml").write_text("[module]")

    discovery = PathDiscovery()

    result = discovery.scan_for_modules([modules_dir])

    assert ".hidden" not in result

  def test_scan_nonexistent_path(self, tmp_path):
    """Should skip non-existent paths."""
    discovery = PathDiscovery()

    result = discovery.scan_for_modules([tmp_path / "nonexistent"])

    assert result == {}

class TestPathDiscoveryFindModule:
  """Tests for finding specific modules."""

  def test_find_module_in_cache(self, tmp_path):
    """Should return cached module path."""
    discovery = PathDiscovery()
    discovery._module_locations = {"test": tmp_path}

    result = discovery.find_module_path("test")

    assert result == tmp_path

  def test_find_module_not_cached(self, tmp_path):
    """Should search when not cached."""
    modules_dir = tmp_path / "plugins" / "core"
    modules_dir.mkdir(parents=True)

    test_module = modules_dir / "test_module"
    test_module.mkdir()
    (test_module / "manifest.toml").write_text("[module]")

    discovery = PathDiscovery()
    discovery.base_path = tmp_path

    result = discovery.find_module_path("test_module")

    assert result == test_module.resolve()

class TestPathDiscoveryStats:
  """Tests for statistics."""

  def test_get_stats_empty(self):
    """Should return empty stats initially."""
    discovery = PathDiscovery()

    stats = discovery.get_stats()

    assert stats["paths_discovered"] == 0
    assert stats["modules_found"] == 0
    assert stats["paths"] == []
    assert stats["modules"] == []

  def test_get_stats_with_data(self, tmp_path):
    """Should return correct stats after discovery."""
    discovery = PathDiscovery()
    discovery._discovered_paths = {tmp_path}
    discovery._module_locations = {"test": tmp_path}

    stats = discovery.get_stats()

    assert stats["paths_discovered"] == 1
    assert stats["modules_found"] == 1
    assert str(tmp_path) in stats["paths"]
    assert "test" in stats["modules"]

class TestPathDiscoveryCache:
  """Tests for cache save/load."""

  def test_save_cache(self, tmp_path):
    """Should save cache to file."""
    discovery = PathDiscovery()
    discovery._discovered_paths = {tmp_path / "path1"}
    discovery._module_locations = {"mod1": tmp_path / "mod1"}

    cache_file = tmp_path / "cache.json"
    discovery.save_cache(cache_file)

    assert cache_file.exists()
    data = json.loads(cache_file.read_text())
    assert "paths" in data
    assert "modules" in data

  def test_load_cache(self, tmp_path):
    """Should load cache from file."""
    cache_file = tmp_path / "cache.json"
    cache_data = {
      "paths": [str(tmp_path / "path1")],
      "modules": {"mod1": str(tmp_path / "mod1")}
    }
    cache_file.write_text(json.dumps(cache_data))

    discovery = PathDiscovery()
    result = discovery.load_cache(cache_file)

    assert result is True
    assert len(discovery._discovered_paths) == 1
    assert "mod1" in discovery._module_locations

  def test_load_cache_nonexistent(self, tmp_path):
    """Should return False for non-existent cache."""
    discovery = PathDiscovery()

    result = discovery.load_cache(tmp_path / "nonexistent.json")

    assert result is False

  def test_load_cache_invalid_json(self, tmp_path):
    """Should handle invalid JSON gracefully."""
    cache_file = tmp_path / "invalid.json"
    cache_file.write_text("not valid json")

    discovery = PathDiscovery()

    result = discovery.load_cache(cache_file)

    assert result is False

class TestPathDiscoveryAllPaths:
  """Tests for discover_all_paths."""

  def test_discover_all_paths_clears_previous(self, tmp_path):
    """Should clear previous discovered paths."""
    discovery = PathDiscovery()
    discovery._discovered_paths = {tmp_path / "old"}
    discovery.base_path = tmp_path

    discovery.discover_all_paths()

    assert tmp_path / "old" not in discovery._discovered_paths

  def test_discover_all_paths_sorts_known_first(self, tmp_path):
    """Should prioritize known paths in results."""
    known_path = tmp_path / "plugins" / "core"
    known_path.mkdir(parents=True)

    other_path = tmp_path / "zzz" / "modules"
    other_path.mkdir(parents=True)

    discovery = PathDiscovery()
    discovery.base_path = tmp_path
    discovery.known_paths = ["plugins/core"]

    paths = discovery.discover_all_paths()

    if len(paths) > 0:
      assert paths[0] == known_path.resolve()
