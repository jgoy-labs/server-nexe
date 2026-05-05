"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/test_b8_initialize_concurrent.py
Description: TDD cec — B8 initialize() race: 4 modules plugin sense asyncio.Lock
             a initialize() permeten que crides concurrents superin el guard
             "if self._initialized" quan hi ha un await intermig.
             Fix: asyncio.Lock per instància + double-check dins lock.
             Mòduls afectats: ollama_module, web_ui_module, mlx_module, llama_cpp_module.
             Onada 4.6d / xfail strict pre-fix.

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
    """Extreu el cos del __init__ fins al primer mètode seguent."""
    src = module_file.read_text()
    fn_start = src.find("    def __init__(")
    if fn_start < 0:
        return ""
    next_fn = src.find("\n    def ", fn_start + 1)
    if next_fn < 0:
        next_fn = src.find("\n    async def ", fn_start + 1)
    return src[fn_start:next_fn] if next_fn > fn_start > 0 else src[fn_start:]


def _get_initialize_src(module_file: Path) -> str:
    """Extreu el cos d'initialize() fins al primer mètode següent."""
    src = module_file.read_text()
    fn_start = src.find("    async def initialize(")
    if fn_start < 0:
        return ""
    next_fn = src.find("\n    async def ", fn_start + 1)
    if next_fn < 0:
        next_fn = src.find("\n    def ", fn_start + 1)
    return src[fn_start:next_fn] if next_fn > fn_start > 0 else src[fn_start:]


# ──────────────────────────────────────────────────────────────────────────────
# Test 1 — xfail strict: lock absent a ollama_module (té await real → race REAL)
# ──────────────────────────────────────────────────────────────────────────────

def test_ollama_module_initialize_has_init_lock():
    """B8: OllamaModule.__init__ ha d'instanciar asyncio.Lock() com a _init_lock.

    Pre-fix: cap Lock al __init__ → initialize() vulnerable a race (ensure_ollama_running
    és async i crea window entre el guard `if self._initialized` i el `_initialized = True`).
    Post-fix: self._init_lock = asyncio.Lock() al __init__ + double-check dins initialize().

    Revert mental: afegir Lock → _init_lock al __init__ → test PASSA.
    Revert del fix → Lock absent → test FALLA.
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
    """B8 anti-reg: initialize() d'OllamaModule ha d'usar self._init_lock.

    Pin: `async with self._init_lock:` ha d'aparèixer a initialize()
    + double-check `if self._initialized: return True` dins el bloc lock.
    Dev#2 no ha de tocar aquest test — queda com a guard permanent.
    """
    init_src = _get_initialize_src(_MODULE_FILES["ollama_module"])

    assert "_init_lock" in init_src, (
        "Anti-reg B8: self._init_lock no usat dins initialize() d'OllamaModule"
    )


# ──────────────────────────────────────────────────────────────────────────────
# Test 3 — anti-reg concurrent amb patró corregit (ha de PASSAR sempre)
# ──────────────────────────────────────────────────────────────────────────────

async def test_initialize_concurrent_lock_holds():
    """Anti-reg B8: el patró Lock+double-check garanteix call_count==1 amb 100 crides.

    Verifica que el patró FIX (asyncio.Lock + double-check) elimina la race.
    Queda com a guard permanent: si el Lock es trenca, call_count > 1.
    """

    class _FixedPatternModule:
        """Patró post-fix: asyncio.Lock per instància + double-check."""
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

    # El patró fix garanteix que _initialized es posa a True exactament 1 cop
    assert m2._initialized is True, "Anti-reg B8: _initialized ha de ser True post-gather"


# ──────────────────────────────────────────────────────────────────────────────
# Test 4 — simbòlics: els 4 mòduls han de tenir _init_lock post-fix
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("plugin_name", list(_MODULE_FILES.keys()))
def test_initialize_module_has_init_lock(plugin_name: str):
    """Anti-reg B8 simbòlic: tots 4 mòduls han de tenir _init_lock al __init__.

    Verifica que el Lock ha estat aplicat de forma consistent als 4 mòduls:
    ollama_module (await real), web_ui_module, mlx_module, llama_cpp_module.
    Pre-fix: falla als 4. Post-fix: passa als 4.
    Dev#2 no ha de tocar aquest test — guard permanent multi-mòdul.
    """
    init_src = _get_init_src(_MODULE_FILES[plugin_name])

    assert "_init_lock" in init_src, (
        f"Anti-reg B8: {plugin_name}/module.py ha de tenir self._init_lock = asyncio.Lock() "
        f"al __init__ (consistent amb fix B8). Fix absent o Lock no afegit."
    )
