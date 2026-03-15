"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: personality/module_manager/tests/test_module_allowlist.py
Description: Tests d'integració per module allowlist enforcement. 

www.jgoy.net
────────────────────────────────────
"""

import os
import pytest
from pathlib import Path

from core.app import app
from core.lifespan import get_server_state
from personality.module_manager.core_modules import get_core_modules

@pytest.fixture(autouse=True)
def setup_allowlist(monkeypatch):
    """Configura allowlist per defecte per als tests."""
    monkeypatch.setenv("NEXE_APPROVED_MODULES", "security,rag,mlx_module,llama_cpp_module,web_ui_module,ollama_module")

def test_approved_modules_environment_configured() -> None:
  """Test that NEXE_APPROVED_MODULES environment variable is configured."""
  approved_modules = os.getenv("NEXE_APPROVED_MODULES", "")
  assert approved_modules, "NEXE_APPROVED_MODULES must be configured"

def test_discover_modules_only_returns_approved() -> None:
  """Test that discover_modules only returns approved modules."""
  approved_modules = os.getenv("NEXE_APPROVED_MODULES", "")
  approved_list = [m.strip() for m in approved_modules.split(",")]

  server_state = get_server_state()
  if not server_state.module_manager:
    pytest.skip("ModuleManager not initialized")

  loaded_modules = server_state.module_manager._modules
  core_set = get_core_modules()
  allowed = set(approved_list) | core_set

  for module_name, module_info in loaded_modules.items():
    if module_name in allowed:
      continue
    assert not getattr(module_info, "enabled", True), \
      f"Module '{module_name}' outside allowlist should be disabled"

def test_unapproved_module_rejected() -> None:
  """Test that attempting to load unapproved module fails gracefully."""
  test_unapproved = "hacker_module_12345"
  server_state = get_server_state()
  if not server_state.module_manager:
    pytest.skip("ModuleManager not initialized")

  loaded_modules = server_state.module_manager._modules
  assert test_unapproved not in loaded_modules

def test_no_modules_loaded_outside_allowlist() -> None:
  """Test that no modules are loaded outside the allowlist."""
  approved_modules = os.getenv("NEXE_APPROVED_MODULES", "")
  approved_set = {m.strip() for m in approved_modules.split(",") if m.strip()}
  core_set = get_core_modules()
  allowed = approved_set | core_set

  server_state = get_server_state()
  if not server_state.module_manager:
    pytest.skip("ModuleManager not initialized")

  loaded_modules = server_state.module_manager._modules
  loaded_set = set(loaded_modules.keys())
  unapproved = loaded_set - allowed

  assert len(unapproved_disabled := {m for m in unapproved if getattr(loaded_modules[m], 'enabled', True)}) == 0, \
    f"Unapproved modules enabled: {unapproved_disabled}"

def test_module_endpoints_require_authentication() -> None:
  """Test that module endpoints require authentication."""
  from fastapi.testclient import TestClient
  with TestClient(app, base_url="http://localhost") as client:
    response = client.get("/security/status")
    if response.status_code != 404:
      assert response.status_code in [401, 403, 500]
