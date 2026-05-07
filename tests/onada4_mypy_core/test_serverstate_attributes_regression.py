"""Anti-regression cluster `ServerState` dynamic attributes (Onada 4.1, BUS Dev#1bis).

Covers mypy findings #45, #46, #47, #65 (`01-classificacio.md`). Currently
the 4 attributes (`_cleanup_task`, `_prewarm_task`, `_session_cleanup_task`,
`configure_modules_callback`) are NOT declared in `ServerState.__init__` —
they are assigned via dynamic `setattr` at `core/lifespan.py:461,467,512` and
`core/server/factory_state.py:42`. Mypy flags `attr-defined`.

The Dev#2 fix (Cluster 1) will add these 4 attributes to `__init__` with default
None and Optional annotation. The observable runtime behaviour must be
stable: the subsequent dynamic assignment continues to work, and the
post-fix default is None.

This test pins two stable runtime contracts across the fix:

1. **Observable default:** `getattr(state, attr, None) is None` — pre-fix is
   None via getattr fallback (attribute absent), post-fix is None via the
   declared default. If Dev#2 inadvertently initialises an attribute to a
   non-None value (e.g. `self._cleanup_task: Task = asyncio.create_task(...)`),
   the test fails.

2. **Runtime settability:** the 4 attributes are settable via setattr and
   retrievable via getattr (exact pattern of lifespan.py:461 etc). Detects
   if Dev#2 introduced a read-only descriptor or a restrictive `__slots__`.

CEC: public instantiation of `ServerState` + getattr/setattr only. No
reading of `lifespan.py` or `factory_state.py` bodies.
"""

from __future__ import annotations

DYNAMIC_ATTRS = (
    "_cleanup_task",
    "_prewarm_task",
    "_session_cleanup_task",
    "configure_modules_callback",
)


def test_serverstate_dynamic_attrs_default_to_none_via_getattr() -> None:
    """Pins contract: pre and post-fix, `getattr(state, attr, None) is None`.

    Pre-fix: attribute does not exist, getattr returns the fallback None.
    Post-fix: attribute exists in __init__ initialised to None.
    Identical observable runtime.
    """
    from core.lifespan import ServerState

    state = ServerState()
    for attr in DYNAMIC_ATTRS:
        assert getattr(state, attr, None) is None, (
            f"ServerState().{attr} (via getattr default=None) = "
            f"{getattr(state, attr, None)!r}, expected None. "
            f"If the Onada 4.1 fix initialises the attribute to a non-None value, "
            f"it breaks the runtime contract with lifespan.py:461,467,512 + "
            f"factory_state.py:42 (which rely on the default being None before "
            f"assigning via setattr)."
        )


def test_serverstate_dynamic_attrs_are_settable_runtime() -> None:
    """Pins contract: the 4 attributes can be assigned via setattr and
    retrieved via getattr (exact pattern of lifespan.py:461 and factory_state.py:42).
    """
    from core.lifespan import ServerState

    state = ServerState()
    sentinel_values = {
        "_cleanup_task": object(),
        "_prewarm_task": object(),
        "_session_cleanup_task": object(),
        "configure_modules_callback": lambda *a, **kw: None,
    }
    for attr, value in sentinel_values.items():
        setattr(state, attr, value)
        assert getattr(state, attr) is value, (
            f"ServerState().{attr} is not settable at runtime — the Onada 4.1 fix "
            f"should keep it settable (lifespan.py:461 etc assigns it "
            f"dynamically)."
        )


def test_serverstate_known_init_attrs_are_present() -> None:
    """Pins contract on the 9 attributes already existing in __init__ (signature
    declared at `core/lifespan.py:185-196` — read-only, not implementation).

    If Dev#2 removes any of these during the Cluster 1/2 fix, the test fails.
    """
    from core.lifespan import ServerState

    state = ServerState()
    expected_existing = (
        "config",
        "api_integrator",
        "project_root",
        "i18n",
        "module_manager",
        "registry",
        "ollama_process",
        "qdrant_available",
        "crypto_provider",
    )
    for attr in expected_existing:
        assert hasattr(state, attr), (
            f"ServerState has lost the existing attribute `{attr}` — "
            f"collateral refactor out of Onada 4.1 scope."
        )
