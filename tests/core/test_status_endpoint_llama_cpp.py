"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/tests/test_status_endpoint_llama_cpp.py
Description: Regression tests for P0-2.c fix — /status endpoint symmetric check
             for llama_cpp. Tests the extracted helper _check_llama_cpp_available()
             which is pure and unit-testable without a real starlette.Request
             (slowapi's @limiter.limit rejects MagicMock).

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import pytest
from unittest.mock import MagicMock

try:
  from core.endpoints.root import _check_llama_cpp_available
except ImportError:
  pytest.skip("_check_llama_cpp_available helper not available", allow_module_level=True)


class TestCheckLlamaCppAvailable:
  """P0-2.c: /status symmetric check via _check_llama_cpp_available() helper."""

  def test_false_when_node_is_none(self):
    """Module present in dict but _node is None → NOT available.

    This catches the ghost-plugin bug: before P0-2.c, /status only checked
    `"llama_cpp_module" in modules` and reported True regardless of whether
    the module had a working backend.
    """
    ghost_plugin = MagicMock()
    ghost_plugin._node = None

    modules = {"llama_cpp_module": ghost_plugin}
    assert _check_llama_cpp_available(modules) is False, (
      "llama_cpp must be reported unavailable when _node is None — "
      "this is the ghost-plugin bug that P0-2.c fixes"
    )

  def test_true_when_node_present(self):
    """Module present with a working _node → available."""
    working_plugin = MagicMock()
    working_plugin._node = MagicMock()  # non-None, truthy

    modules = {"llama_cpp_module": working_plugin}
    assert _check_llama_cpp_available(modules) is True

  def test_false_when_module_absent(self):
    """Module not in dict at all (e.g., popped by P0-2.b loader fix) → False."""
    # Only ollama loaded, no llama_cpp
    modules = {"ollama_module": MagicMock()}
    assert _check_llama_cpp_available(modules) is False

  def test_false_when_instance_has_no_node_attr(self):
    """Defensive: if the plugin doesn't even have _node attribute, return False.

    Prevents AttributeError if a future plugin class is misshapen.
    """
    weird_plugin = object()  # no attributes at all
    modules = {"llama_cpp_module": weird_plugin}
    assert _check_llama_cpp_available(modules) is False
