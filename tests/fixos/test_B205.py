"""
────────────────────────────────────
Server Nexe
Location: tests/fixos/test_B205.py
Description: TDD fix for B205 — /v1/memory/store sense rate limit mentre /search en te.
────────────────────────────────────
"""


def test_memory_store_is_rate_limited():
    """B205: memory_store ha d'estar registrat al limiter (slowapi route_limits)."""
    from core.dependencies import limiter
    from memory.memory.api import v1  # noqa: F401 (side-effect: registers routes + limits)

    store_fn = v1.memory_store
    store_key = f"{store_fn.__module__}.{store_fn.__qualname__}"

    assert store_key in limiter._route_limits, (
        f"B205: memory_store ({store_key}) no esta registrat al limiter. "
        f"Claus registrades: {list(limiter._route_limits.keys())}"
    )


def test_memory_store_has_wrapped_attribute():
    """B205: @limiter.limit embolcalla la funcio — __wrapped__ ha d'existir."""
    from memory.memory.api import v1

    assert hasattr(v1.memory_store, "__wrapped__"), (
        "B205: memory_store no te __wrapped__ — @limiter.limit no s'ha aplicat"
    )


def test_memory_search_still_rate_limited():
    """Regressio: /search segueix tenint rate limit (no hem trencat res)."""
    from core.dependencies import limiter
    from memory.memory.api import v1  # noqa: F401

    search_fn = v1.memory_search
    search_key = f"{search_fn.__module__}.{search_fn.__qualname__}"

    assert search_key in limiter._route_limits, (
        f"Regressio: memory_search ({search_key}) ha perdut el rate limit"
    )
