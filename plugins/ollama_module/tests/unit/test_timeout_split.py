"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: plugins/ollama_module/tests/unit/test_timeout_split.py
Description: Regression tests for P0-1 fix — httpx.Timeout split for OllamaChat and OllamaModels.
             Verifies that _timeout property returns httpx.Timeout object with correct
             connect/read/write/pool values, and that owner.timeout override still works.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import pytest
from unittest.mock import patch, MagicMock

try:
  import httpx
  from plugins.ollama_module.core.chat import OllamaChat
  from plugins.ollama_module.core.models import OllamaModels
except ImportError:
  pytest.skip("OllamaChat/OllamaModels not available", allow_module_level=True)


@pytest.fixture
def clean_env(monkeypatch):
  """Clear all NEXE_OLLAMA_*_TIMEOUT env vars to test defaults."""
  for var in [
    "NEXE_OLLAMA_CONNECT_TIMEOUT",
    "NEXE_OLLAMA_READ_TIMEOUT",
    "NEXE_OLLAMA_MODELS_READ_TIMEOUT",
    "NEXE_OLLAMA_WRITE_TIMEOUT",
    "NEXE_OLLAMA_POOL_TIMEOUT",
  ]:
    monkeypatch.delenv(var, raising=False)


@pytest.fixture
def mock_parent_with_httpx():
  """Mock _parent() to return an object with real httpx module attached."""
  mock_parent = MagicMock()
  mock_parent.httpx = httpx
  return mock_parent


class TestOllamaChatTimeoutSplit:
  """P0-1: OllamaChat._timeout returns httpx.Timeout with split values."""

  def test_default_returns_httpx_Timeout_object(self, clean_env, mock_parent_with_httpx):
    """Default _timeout should be httpx.Timeout(connect=5, read=600, write=10, pool=5)."""
    chat = OllamaChat(client=MagicMock())
    with patch(
      "plugins.ollama_module.core.chat._parent",
      return_value=mock_parent_with_httpx,
    ):
      timeout = chat._timeout

    assert isinstance(timeout, httpx.Timeout), (
      f"Expected httpx.Timeout object, got {type(timeout).__name__}"
    )
    assert timeout.connect == 5.0, "Chat connect timeout must be 5s (fast fail on Ollama down)"
    assert timeout.read == 600.0, "Chat read timeout must be 600s (support thinking models)"
    assert timeout.write == 10.0
    assert timeout.pool == 5.0

  def test_env_var_override_respected(self, monkeypatch, mock_parent_with_httpx):
    """Env vars should override defaults."""
    monkeypatch.setenv("NEXE_OLLAMA_CONNECT_TIMEOUT", "3.0")
    monkeypatch.setenv("NEXE_OLLAMA_READ_TIMEOUT", "120.0")

    chat = OllamaChat(client=MagicMock())
    with patch(
      "plugins.ollama_module.core.chat._parent",
      return_value=mock_parent_with_httpx,
    ):
      timeout = chat._timeout

    assert timeout.connect == 3.0
    assert timeout.read == 120.0

  def test_owner_timeout_override_still_works(self, clean_env, mock_parent_with_httpx):
    """If owner.timeout is set, it takes precedence over defaults (back-compat)."""
    owner_timeout = httpx.Timeout(connect=1.0, read=1.0, write=1.0, pool=1.0)
    owner = MagicMock()
    owner.timeout = owner_timeout

    chat = OllamaChat(client=MagicMock())
    chat._owner = owner

    with patch(
      "plugins.ollama_module.core.chat._parent",
      return_value=mock_parent_with_httpx,
    ):
      timeout = chat._timeout

    assert timeout is owner_timeout, "owner.timeout must short-circuit the property"


class TestOllamaModelsTimeoutSplit:
  """P0-1: OllamaModels._timeout returns httpx.Timeout with split values (read=60s)."""

  def test_default_returns_httpx_Timeout_object(self, clean_env, mock_parent_with_httpx):
    """Default _timeout should be httpx.Timeout(connect=5, read=60, write=10, pool=5)."""
    models_obj = OllamaModels(client=MagicMock())
    with patch(
      "plugins.ollama_module.core.models._parent",
      return_value=mock_parent_with_httpx,
    ):
      timeout = models_obj._timeout

    assert isinstance(timeout, httpx.Timeout), (
      f"Expected httpx.Timeout object, got {type(timeout).__name__}"
    )
    assert timeout.connect == 5.0, "Models connect timeout must be 5s"
    assert timeout.read == 60.0, "Models read timeout must be 60s (list/info/delete are fast)"
    assert timeout.write == 10.0
    assert timeout.pool == 5.0

  def test_models_read_env_var_override(self, monkeypatch, mock_parent_with_httpx):
    """NEXE_OLLAMA_MODELS_READ_TIMEOUT should override default 60s."""
    monkeypatch.setenv("NEXE_OLLAMA_MODELS_READ_TIMEOUT", "30.0")

    models_obj = OllamaModels(client=MagicMock())
    with patch(
      "plugins.ollama_module.core.models._parent",
      return_value=mock_parent_with_httpx,
    ):
      timeout = models_obj._timeout

    assert timeout.read == 30.0

  def test_owner_timeout_override_still_works(self, clean_env, mock_parent_with_httpx):
    """owner.timeout override (back-compat)."""
    owner_timeout = httpx.Timeout(connect=1.0, read=1.0, write=1.0, pool=1.0)
    owner = MagicMock()
    owner.timeout = owner_timeout

    models_obj = OllamaModels(client=MagicMock())
    models_obj._owner = owner

    with patch(
      "plugins.ollama_module.core.models._parent",
      return_value=mock_parent_with_httpx,
    ):
      timeout = models_obj._timeout

    assert timeout is owner_timeout

  def test_pull_timeout_unchanged(self, clean_env):
    """_pull_timeout property must remain as float (NOT touched by P0-1 fix)."""
    models_obj = OllamaModels(client=MagicMock())
    # Default path (no owner): returns 600.0 as float
    pull_timeout = models_obj._pull_timeout
    assert pull_timeout == 600.0
    assert isinstance(pull_timeout, float)
