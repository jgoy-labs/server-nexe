"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: plugins/llama_cpp_module/tests/test_initialize_import_check.py
Description: Regression tests for P0-2.a fix — LlamaCppModule.initialize() must
             verify `import llama_cpp` succeeds before proceeding, and return False
             (triggering loader pop from P0-2.b) if the native lib is missing.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import sys
import pytest

try:
  from plugins.llama_cpp_module.module import LlamaCppModule
except ImportError:
  pytest.skip("LlamaCppModule not available", allow_module_level=True)


@pytest.fixture
def no_llama_cpp(monkeypatch):
  """Force ImportError on `import llama_cpp`.

  Setting sys.modules['llama_cpp'] = None makes Python raise ImportError with
  message "import of llama_cpp halted; None in sys.modules" on any subsequent
  `import llama_cpp` statement in the module under test.
  """
  monkeypatch.setitem(sys.modules, "llama_cpp", None)
  yield


@pytest.fixture
def fresh_module():
  """Build a fresh LlamaCppModule (unitialized)."""
  return LlamaCppModule()


class TestInitializeImportCheck:
  """P0-2.a: LlamaCppModule.initialize() verifies llama_cpp import."""

  @pytest.mark.asyncio
  async def test_initialize_returns_false_when_llama_cpp_missing(
    self, no_llama_cpp, fresh_module
  ):
    """When `import llama_cpp` fails, initialize() must return False."""
    result = await fresh_module.initialize(context={})
    assert result is False, (
      "initialize() must return False when llama-cpp-python is missing "
      "(so that the loader P0-2.b can pop the module from app.state.modules)"
    )
    assert fresh_module._initialized is False, (
      "self._initialized must stay False so /status symmetric check (P0-2.c) "
      "reports llama_cpp as unavailable"
    )

  @pytest.mark.asyncio
  async def test_initialize_kept_node_none_when_import_fails(
    self, no_llama_cpp, fresh_module
  ):
    """self._node must stay None when the import check fails (no ghost node)."""
    await fresh_module.initialize(context={})
    assert fresh_module._node is None, (
      "self._node must be None after failed initialize — this is what the "
      "/status symmetric check (P0-2.c) inspects to report engines_available"
    )

  @pytest.mark.asyncio
  async def test_initialize_kept_router_none_when_import_fails(
    self, no_llama_cpp, fresh_module
  ):
    """self._router must stay None — no ghost routes created when lib is missing.

    Design choice: the import check runs BEFORE _init_router() to avoid
    creating phantom routes that would appear in the router tree but have
    no working backend. A dev inspecting `/routes` should not see a
    llama_cpp path when the library is absent.
    """
    await fresh_module.initialize(context={})
    assert fresh_module._router is None, (
      "self._router must be None after failed import check — routes are NOT "
      "created when the native lib is missing"
    )

  @pytest.mark.asyncio
  async def test_initialize_proceeds_past_import_check_when_lib_available(
    self, fresh_module
  ):
    """When llama_cpp is importable, initialize() must proceed past the check.

    Skipped automatically if llama-cpp-python is not installed in the venv
    running the tests.
    """
    try:
      import llama_cpp  # noqa: F401
    except ImportError:
      pytest.skip("llama-cpp-python not installed in this venv")

    # The init path may still fail (e.g., invalid model path), but it must
    # progress past the import check — meaning self._router should be set
    # (because _init_router() runs after the import check).
    await fresh_module.initialize(context={})
    # Either _initialized is True (full success) OR _router is not None
    # (import check passed, subsequent steps may have failed gracefully).
    assert fresh_module._router is not None or fresh_module._initialized, (
      "When llama_cpp is importable, initialize() must get past the import "
      "check and at least set _router (via _init_router())"
    )
