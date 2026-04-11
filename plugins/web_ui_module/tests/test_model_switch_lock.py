"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: plugins/web_ui_module/tests/test_model_switch_lock.py
Description: Regression tests for P0-3 fix — short async lock around body.model
             singleton mutations in routes_chat.py. These are source-level
             verification tests because the full _chat_inner flow is too
             coupled to the FastAPI/slowapi stack to unit-test directly.

             For live behavior verification (concurrent body.model requests),
             see the session-3 re-auditoria via Playwright.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import re
import asyncio
from pathlib import Path

import pytest


# Resolve the routes_chat.py source path from this test location
# (tests/test_model_switch_lock.py → ../api/routes_chat.py)
ROUTES_CHAT_PATH = Path(__file__).resolve().parents[1] / "api" / "routes_chat.py"


@pytest.fixture(scope="module")
def routes_chat_source():
  """Load routes_chat.py source once per module."""
  if not ROUTES_CHAT_PATH.exists():
    pytest.skip(f"routes_chat.py not found at {ROUTES_CHAT_PATH}")
  return ROUTES_CHAT_PATH.read_text()


class TestModelSwitchLockPresence:
  """P0-3: verify the lock is declared and wraps the body.model block."""

  def test_lock_declared_in_register_chat_routes(self, routes_chat_source):
    """`_MODEL_SWITCH_LOCK = asyncio.Lock()` must be declared in the source.

    Declared inside register_chat_routes() alongside _chat_semaphore so it
    is captured as a closure by the nested _chat_inner function.
    """
    assert "_MODEL_SWITCH_LOCK = asyncio.Lock()" in routes_chat_source, (
      "P0-3 fix missing: _MODEL_SWITCH_LOCK asyncio.Lock() not declared. "
      "Expected at register_chat_routes() scope, alongside _chat_semaphore."
    )

  def test_lock_wraps_body_model_mutation_block(self, routes_chat_source):
    """`async with _MODEL_SWITCH_LOCK:` must directly follow `if body.get("model"):`.

    This ensures the lock is acquired BEFORE any singleton mutation happens
    (os.environ, engine._node.config, LlamaCppChatNode._pool, etc.).
    """
    # Match: `if body.get("model"):` then (any whitespace/newlines) then `async with _MODEL_SWITCH_LOCK:`
    pattern = re.compile(
      r'if body\.get\("model"\):\s*\n\s*async with _MODEL_SWITCH_LOCK:',
      re.MULTILINE,
    )
    assert pattern.search(routes_chat_source), (
      "P0-3 fix missing: `async with _MODEL_SWITCH_LOCK:` does not directly "
      "follow `if body.get(\"model\"):`. The lock must wrap the entire "
      "singleton mutation block to serialize concurrent swaps."
    )

  def test_lock_scope_includes_singleton_mutations(self, routes_chat_source):
    """The mutations of class-level singletons must be INSIDE the lock scope.

    This test verifies specific mutation lines appear after the `async with`
    declaration — a basic sanity check that re-indentation was done correctly.
    """
    # Find the lock line and everything after it up to "Calling {engine_name}.chat"
    match = re.search(
      r'async with _MODEL_SWITCH_LOCK:.*?logger\.info\(f"Calling \{engine_name\}',
      routes_chat_source,
      re.DOTALL,
    )
    assert match, "Could not find lock scope boundary in routes_chat.py"
    scope = match.group(0)

    # These mutations must be inside the locked scope
    expected_patterns = [
      'os.environ["NEXE_MLX_MODEL"]',
      'engine._node.__class__._config',
      'LlamaCppChatNode._pool.destroy_all()',
      'LlamaCppChatNode._pool = ModelPool(new_config)',
    ]
    for pat in expected_patterns:
      assert pat in scope, (
        f"P0-3 fix incomplete: mutation `{pat}` must be inside the "
        f"`async with _MODEL_SWITCH_LOCK:` block, but was not found in scope"
      )


class TestAsyncLockReleaseContract:
  """Sanity: asyncio.Lock() always releases on exception (Python contract)."""

  @pytest.mark.asyncio
  async def test_async_lock_released_on_exception(self):
    """Document that `async with asyncio.Lock()` releases even if body raises.

    This isn't testing our code directly — it's testing the contract we rely
    on. If Python's asyncio.Lock ever changed this behavior, our P0-3 fix
    would deadlock on the next request after any exception inside the block.
    """
    lock = asyncio.Lock()

    with pytest.raises(RuntimeError, match="boom"):
      async with lock:
        assert lock.locked(), "Lock should be held inside the async with block"
        raise RuntimeError("boom")

    assert not lock.locked(), (
      "asyncio.Lock MUST be released after exception inside async with. "
      "If this test fails, Python's contract has changed and P0-3 needs review."
    )
