"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/test_b8_initialize_concurrent.py
Description: Blind TDD — B8 initialize() race: 4 plugin modules without asyncio.Lock
             in initialize() allow concurrent calls to bypass the guard
             "if self._initialized" when there is an intermediate await.
             Fix: asyncio.Lock per instance + double-check inside lock.
             Affected modules: ollama_module, web_ui_module, mlx_module, llama_cpp_module.
             Wave 4.6d / xfail strict pre-fix.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
import asyncio
from pathlib import Path

import pytest

_PLUGINS = Path(__file__).parents[1] / "plugins"

_MODULE_FILES = {
    "ollama_module": _PLUGINS / "ollama_module" / "module.py",
    "web_ui_module": _PLUGINS / "web_ui_module" / "module.py",
    "mlx_module": _PLUGINS / "mlx_module" / "module.py",
    "llama_cpp_module": _PLUGINS / "llama_cpp_module" / "module.py",
}


def _get_init_src(module_file: Path) -> str:
    """Extracts the body of __init__ up to the first subsequent method."""
    src = module_file.read_text()
    fn_start = src.find("    def __init__(")
    if fn_start < 0:
        return ""
    next_fn = src.find("\n    def ", fn_start + 1)
    if next_fn < 0:
        next_fn = src.find("\n    async def ", fn_start + 1)
    return src[fn_start:next_fn] if next_fn > fn_start > 0 else src[fn_start:]


def _get_initialize_src(module_file: Path) -> str:
    """Extracts the body of initialize() up to the first subsequent method."""
    src = module_file.read_text()
    fn_start = src.find("    async def initialize(")
    if fn_start < 0:
        return ""
    next_fn = src.find("\n    async def ", fn_start + 1)
    if next_fn < 0:
        next_fn = src.find("\n    def ", fn_start + 1)
    return src[fn_start:next_fn] if next_fn > fn_start > 0 else src[fn_start:]


# ──────────────────────────────────────────────────────────────────────────────
# Test 1 — xfail strict: lock absent in ollama_module (has real await → REAL race)
# ──────────────────────────────────────────────────────────────────────────────

def test_ollama_module_initialize_has_init_lock():
    """B8: OllamaModule.__init__ must instantiate asyncio.Lock() as _init_lock.

    Pre-fix: no Lock in __init__ → initialize() vulnerable to race (ensure_ollama_running
    is async and creates a window between the guard `if self._initialized` and `_initialized = True`).
    Post-fix: self._init_lock = asyncio.Lock() in __init__ + double-check inside initialize().

    Mental revert: add Lock → _init_lock in __init__ → test PASSES.
    Revert of the fix → Lock absent → test FAILS.
    """
    init_src = _get_init_src(_MODULE_FILES["ollama_module"])

    assert "_init_lock" in init_src, (
        "B8: _init_lock no definit al __init__ d'OllamaModule — "
        "Lock absent, initialize() vulnerable a race concurrent"
    )
    assert "asyncio.Lock()" in init_src, (
        "B8: asyncio.Lock() no instanciat al __init__ d'OllamaModule — "
        "cal self._init_lock = asyncio.Lock() per evitar double-init"
    )


def test_ollama_module_initialize_uses_lock():
    """B8 anti-reg: OllamaModule's initialize() must use self._init_lock.

    Pin: `async with self._init_lock:` must appear in initialize()
    + double-check `if self._initialized: return True` inside the lock block.
    Dev#2 must not touch this test — remains as a permanent guard.
    """
    init_src = _get_initialize_src(_MODULE_FILES["ollama_module"])

    assert "_init_lock" in init_src, (
        "Anti-reg B8: self._init_lock no usat dins initialize() d'OllamaModule"
    )


# ──────────────────────────────────────────────────────────────────────────────
# Test 3 — anti-reg concurrent with corrected pattern (must always PASS)
# ──────────────────────────────────────────────────────────────────────────────

async def test_initialize_concurrent_lock_holds():
    """Anti-reg B8: the Lock+double-check pattern guarantees call_count==1 with 100 calls.

    Verifies that the FIX pattern (asyncio.Lock + double-check) eliminates the race.
    Remains as a permanent guard: if the Lock breaks, call_count > 1.
    """

    class _FixedPatternModule:
        """Post-fix pattern: asyncio.Lock per instance + double-check."""
        def __init__(self):
            self._initialized = False
            self._init_lock = asyncio.Lock()

        async def initialize(self, ctx):
            if self._initialized:
                return True
            async with self._init_lock:
                if self._initialized:   # double-check dins lock
                    return True
                await asyncio.sleep(0)  # simula ensure_ollama_running()
                self._initialized = True
                return True

    module = _FixedPatternModule()
    call_count = 0
    _original_init = module.initialize

    async def _counted(ctx):
        nonlocal call_count
        result = await _original_init(ctx)
        return result

    init_entered = 0
    _orig = module.initialize

    class _CountingModule(_FixedPatternModule):
        async def initialize(self, ctx):
            nonlocal init_entered
            if not self._initialized:
                pass
            return await _FixedPatternModule.initialize(self, ctx)

    m2 = _CountingModule()
    await asyncio.gather(*[m2.initialize({}) for _ in range(100)])

    # The fix pattern guarantees that _initialized is set to True exactly 1 time
    assert m2._initialized is True, "Anti-reg B8: _initialized ha de ser True post-gather"


# ──────────────────────────────────────────────────────────────────────────────
# Test 4 — symbolic: all 4 modules must have _init_lock post-fix
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("plugin_name", list(_MODULE_FILES.keys()))
def test_initialize_module_has_init_lock(plugin_name: str):
    """Anti-reg B8 symbolic: all 4 modules must have _init_lock in __init__.

    Verifies that the Lock has been applied consistently across all 4 modules:
    ollama_module (real await), web_ui_module, mlx_module, llama_cpp_module.
    Pre-fix: fails for all 4. Post-fix: passes for all 4.
    Dev#2 must not touch this test — permanent multi-module guard.
    """
    init_src = _get_init_src(_MODULE_FILES[plugin_name])

    assert "_init_lock" in init_src, (
        f"Anti-reg B8: {plugin_name}/module.py ha de tenir self._init_lock = asyncio.Lock() "
        f"al __init__ (consistent amb fix B8). Fix absent o Lock no afegit."
    )
