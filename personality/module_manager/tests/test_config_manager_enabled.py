"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: personality/config/tests/test_config_manager_enabled.py
Description: Tests per ConfigManager amb suport list+dict de mòduls enabled. Valida formats globals, per-module, prioritats i edge cases.

www.jgoy.net
────────────────────────────────────
"""

import pytest
from pathlib import Path
from personality.module_manager.config_manager import ConfigManager
from personality.data.models import ModuleInfo, ModuleState

@pytest.fixture
def mock_module_info():
  """Fixture que crea un ModuleInfo bàsic per tests"""
  def _create(name="test_module", enabled=True, priority=10):
    fake_path = Path(f"/fake/path/{name}")
    info = ModuleInfo(
      name=name,
      path=fake_path,
      manifest_path=fake_path / "manifest.toml",
      manifest={
        'module': {
          'enabled': enabled,
          'priority': priority,
          'auto_start': False
        }
      }
    )
    return info
  return _create

def test_config_global_enabled_list(mock_module_info):
  """
  Test FORMAT 1: Global enabled list.

  M-2: [plugins.modules] enabled = ["security", "rag"]
  """
  config_data = {
    "plugins": {
      "modules": {
        "enabled": ["security", "rag"]
      }
    }
  }

  config_manager = ConfigManager(None)
  config_manager._config = config_data

  security_info = mock_module_info(name="security")
  config_manager.apply_config_to_module(security_info)
  assert security_info.enabled == True
  assert security_info.state != ModuleState.DISABLED

  obs_info = mock_module_info(name="observability")
  config_manager.apply_config_to_module(obs_info)
  assert obs_info.enabled == False
  assert obs_info.state == ModuleState.DISABLED

def test_config_per_module_dict(mock_module_info):
  """
  Test FORMAT 2: Per-module dict.

  M-2: [plugins.modules.security] enabled = true
  """
  config_data = {
    "plugins": {
      "modules": {
        "security": {"enabled": True, "priority": 5},
        "rag": {"enabled": False}
      }
    }
  }

  config_manager = ConfigManager(None)
  config_manager._config = config_data

  security_info = mock_module_info(name="security")
  config_manager.apply_config_to_module(security_info)
  assert security_info.enabled == True
  assert security_info.priority == 5

  rag_info = mock_module_info(name="rag")
  config_manager.apply_config_to_module(rag_info)
  assert rag_info.enabled == False
  assert rag_info.state == ModuleState.DISABLED

def test_config_dict_overrides_list(mock_module_info):
  """
  Test prioritat: dict > list.

  M-2: Si hi ha ambdós formats, dict té prioritat (més específic).
  """
  config_data = {
    "plugins": {
      "modules": {
        "enabled": ["security", "rag"],
        "rag": {"enabled": False}
      }
    }
  }

  config_manager = ConfigManager(None)
  config_manager._config = config_data

  security_info = mock_module_info(name="security")
  config_manager.apply_config_to_module(security_info)
  assert security_info.enabled == True

  rag_info = mock_module_info(name="rag")
  config_manager.apply_config_to_module(rag_info)
  assert rag_info.enabled == False

def test_config_dict_overrides_list_edge_case(mock_module_info):
  """
  Test cas límit: dict enabled=true OVERRIDE list que NO l'inclou.

  M-2 BUG FIX: Si module NO està a list, però dict diu enabled=true,
  dict té prioritat (més específic guanya sempre).
  """
  config_data = {
    "plugins": {
      "modules": {
        "enabled": ["security"],
        "observability": {"enabled": True}
      }
    }
  }

  config_manager = ConfigManager(None)
  config_manager._config = config_data

  security_info = mock_module_info(name="security")
  config_manager.apply_config_to_module(security_info)
  assert security_info.enabled == True

  obs_info = mock_module_info(name="observability")
  config_manager.apply_config_to_module(obs_info)
  assert obs_info.enabled == True
  assert obs_info.state != ModuleState.DISABLED

def test_config_no_enabled_key_uses_manifest(mock_module_info):
  """Fallback a manifest si no hi ha config."""
  config_data = {"plugins": {"modules": {}}}
  config_manager = ConfigManager(None)
  config_manager._config = config_data

  module_enabled = mock_module_info(name="test", enabled=True)
  config_manager.apply_config_to_module(module_enabled)
  assert module_enabled.enabled == True

def test_config_empty_list_disables_all(mock_module_info):
  """Llista buida desactiva tot."""
  config_data = {"plugins": {"modules": {"enabled": []}}}
  config_manager = ConfigManager(None)
  config_manager._config = config_data

  security_info = mock_module_info(name="security")
  config_manager.apply_config_to_module(security_info)
  assert security_info.enabled == False

def test_config_list_with_whitespace(mock_module_info):
  """Comparació exacta de noms."""
  config_data = {"plugins": {"modules": {"enabled": ["security", " rag "]}}}
  config_manager = ConfigManager(None)
  config_manager._config = config_data

  security_info = mock_module_info(name="security")
  config_manager.apply_config_to_module(security_info)
  assert security_info.enabled == True

  rag_info = mock_module_info(name="rag")
  config_manager.apply_config_to_module(rag_info)
  assert rag_info.enabled == False

def test_config_dict_with_other_settings(mock_module_info):
  """Configuració de priority i auto_start."""
  config_data = {
    "plugins": {
      "modules": {
        "security": {"enabled": True, "priority": 100, "auto_start": True}
      }
    }
  }
  config_manager = ConfigManager(None)
  config_manager._config = config_data

  security_info = mock_module_info(name="security", priority=10)
  config_manager.apply_config_to_module(security_info)
  assert security_info.enabled == True
  assert security_info.priority == 100
  assert security_info.auto_start == True

def test_config_mixed_format(mock_module_info):
  """Format mixt list + dict."""
  config_data = {
    "plugins": {
      "modules": {
        "enabled": ["security", "rag", "observability"],
        "security": {"priority": 1, "auto_start": True},
        "rag": {"enabled": False}
      }
    }
  }
  config_manager = ConfigManager(None)
  config_manager._config = config_data

  security_info = mock_module_info(name="security")
  config_manager.apply_config_to_module(security_info)
  assert security_info.enabled == True
  assert security_info.priority == 1

  rag_info = mock_module_info(name="rag")
  config_manager.apply_config_to_module(rag_info)
  assert rag_info.enabled == False

def test_config_case_sensitive_module_names(mock_module_info):
  """Case-sensitive names."""
  config_data = {"plugins": {"modules": {"enabled": ["Security"]}}}
  config_manager = ConfigManager(None)
  config_manager._config = config_data

  security_upper = mock_module_info(name="Security")
  config_manager.apply_config_to_module(security_upper)
  assert security_upper.enabled == True

  security_lower = mock_module_info(name="security")
  config_manager.apply_config_to_module(security_lower)
  assert security_lower.enabled == False

def test_config_loads_from_toml_list_format(tmp_path):
  """Carregar list des de TOML."""
  config_file = tmp_path / "server.toml"
  config_file.write_text("[plugins.modules]\nenabled = [\"security\", \"rag\"]")
  config_manager = ConfigManager(config_file)
  assert config_manager._config['plugins']['modules']['enabled'] == ["security", "rag"]

def test_config_loads_from_toml_dict_format(tmp_path):
  """Carregar dict des de TOML."""
  config_file = tmp_path / "server.toml"
  config_file.write_text("[plugins.modules.security]\nenabled = true\npriority = 5\n\n[plugins.modules.rag]\nenabled = false")
  config_manager = ConfigManager(config_file)
  modules = config_manager._config['plugins']['modules']
  assert modules['security']['enabled'] == True
  assert modules['rag']['enabled'] == False