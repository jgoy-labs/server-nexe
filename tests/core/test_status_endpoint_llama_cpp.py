"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/tests/test_status_endpoint_llama_cpp.py
Description: Node-aware llama_cpp availability regression tests. Originally
             P0-2.c covered the extracted helper _check_llama_cpp_available();
             B260 consolidated that node check into the SINGLE source of truth
             routing._engine_available() (used by both chat routing and /status),
             so these tests now exercise the canonical function. The ghost-plugin
             semantics (key present but _node is None → unavailable) are preserved.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from unittest.mock import MagicMock

from core.endpoints.chat_engines.routing import _engine_available


def _state(modules):
  app_state = MagicMock()
  app_state.modules = modules
  return app_state


class TestLlamaCppNodeAwareAvailability:
  """B260 (ex P0-2.c): /status + chat share routing._engine_available."""

  def test_false_when_node_is_none(self):
    """Module present in dict but _node is None → NOT available.

    The ghost-plugin bug: before the node check, availability was reported by
    ``"llama_cpp_module" in modules`` regardless of a working backend.
    """
    ghost_plugin = MagicMock()
    ghost_plugin._node = None
    assert _engine_available("llama_cpp", _state({"llama_cpp_module": ghost_plugin})) is False, (
      "llama_cpp must be unavailable when _node is None — the ghost-plugin bug"
    )

  def test_true_when_node_present(self):
    """Module present with a working _node → available."""
    working_plugin = MagicMock()
    working_plugin._node = MagicMock()  # non-None, truthy
    assert _engine_available("llama_cpp", _state({"llama_cpp_module": working_plugin})) is True

  def test_false_when_module_absent(self):
    """Module not in dict at all (e.g., popped by the loader) → False."""
    assert _engine_available("llama_cpp", _state({"ollama_module": MagicMock()})) is False

  def test_false_when_instance_has_no_node_attr(self):
    """Defensive: a plugin without a _node attribute returns False (no AttributeError)."""
    weird_plugin = object()  # no attributes at all
    assert _engine_available("llama_cpp", _state({"llama_cpp_module": weird_plugin})) is False
