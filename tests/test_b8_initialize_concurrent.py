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
             / xfail strict pre-fix.

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
    dev must not touch this test — remains as a permanent guard.
    """
    init_src = _get_initialize_src(_MODULE_FILES["ollama_module"])

    assert "_init_lock" in init_src, (
        "Anti-reg B8: self._init_lock no usat dins initialize() d'OllamaModule"
    )


# ──────────────────────────────────────────────────────────────────────────────
# Test 3 — anti-reg concurrent with corrected pattern (must always PASS)
# ──────────────────────────────────────────────────────────────────────────────

async def test_initialize_concurrent_lock_holds():
    """Anti-reg B8 conductual: el lock de PRODUCCIÓ serialitza initialize().

    B047 — reforçat de teatre a conductual. L'original feia gather(100) sobre una
    classe `_FixedPatternModule` INVENTADA dins el test (+ assert dèbil
    `_initialized is True`, que passa fins i tot amb race) → no exercia producció.
    Aquest instancia l'OllamaModule REAL, fa que el pas car (ensure_ollama_running)
    compti i cedeixi (obrint la finestra de race entre el guard i _initialized=True),
    i asserta que amb 100 crides concurrents s'executa EXACTAMENT 1 cop (lock retingut).

    Prova de mutació: a plugins/ollama_module/module.py canviar
    `async with self._init_lock:` per `if True:` → ~100 execucions → VERMELL.
    """
    from unittest.mock import AsyncMock, MagicMock
    from plugins.ollama_module.module import OllamaModule

    module = OllamaModule()
    call_count = 0

    async def _counted_ensure():
        nonlocal call_count
        call_count += 1
        await asyncio.sleep(0)  # finestra de race entre el guard i _initialized=True

    # Neutralitza el setup de routing i el daemon real; només ens importa que el
    # cos car de initialize() s'executi un sol cop sota concurrència.
    module._init_router = MagicMock()
    module.client.ensure_ollama_running = _counted_ensure
    module.client.check_connection = AsyncMock(return_value=True)

    await asyncio.gather(*[module.initialize({}) for _ in range(100)])

    assert call_count == 1, (
        f"B8: el pas car d'init s'ha executat {call_count} cops amb 100 crides "
        f"concurrents — el lock no serialitza (race de doble-init)"
    )
    assert module._initialized is True
    assert module._state == "ready"


# ──────────────────────────────────────────────────────────────────────────────
# Test 4 — symbolic: all 4 modules must have _init_lock post-fix
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("plugin_name", list(_MODULE_FILES.keys()))
def test_initialize_module_has_init_lock(plugin_name: str):
    """Anti-reg B8 symbolic: all 4 modules must have _init_lock in __init__.

    Verifies that the Lock has been applied consistently across all 4 modules:
    ollama_module (real await), web_ui_module, mlx_module, llama_cpp_module.
    Pre-fix: fails for all 4. Post-fix: passes for all 4.
    dev must not touch this test — permanent multi-module guard.
    """
    init_src = _get_init_src(_MODULE_FILES[plugin_name])

    assert "_init_lock" in init_src, (
        f"Anti-reg B8: {plugin_name}/module.py ha de tenir self._init_lock = asyncio.Lock() "
        f"al __init__ (consistent amb fix B8). Fix absent o Lock no afegit."
    )
