"""
Cluster 3 (L331) — path_discovery.find_module_path signature Optional[Path].

The current signature declares -> Path, but the body returns modules.get(module_name)
which is Path | None. The docstring already confirms "Module path or None".

Contract pin: find_module_path('non_existent_module') returns None without crash.
The mypy fix (changing -> Path to -> Optional[Path]) must NOT break this contract.
"""
from pathlib import Path


def test_cluster3_find_module_path_inexistent_returns_none():
    """Anti-regression: find_module_path with non-existent module returns None, not crash.

    PASSES pre-fix (runtime behaviour already correct).
    FAILS if Dev#2 changes the implementation to raise or return non-None for unknown modules.
    """
    from personality.module_manager.path_discovery import PathDiscovery

    pd = PathDiscovery()
    result = pd.find_module_path("__module_that_does_not_exist_onada4__")

    assert result is None, (
        f"find_module_path returns {result!r} instead of None — "
        "Optional[Path] contract broken (Cluster 3 Onada 4.3)"
    )


def test_cluster3_find_module_path_signature_accepts_str():
    """Anti-regression: find_module_path accepts a str as the only positional argument.

    Pins that the public signature does not add new mandatory parameters (Dev#2 mypy scope).
    """
    import inspect
    from personality.module_manager.path_discovery import PathDiscovery

    sig = inspect.signature(PathDiscovery.find_module_path)
    params = list(sig.parameters.keys())

    assert "module_name" in params, (
        f"Parameter 'module_name' has disappeared from find_module_path — signature broken. "
        f"Current parameters: {params}"
    )
    assert params[1] == "module_name", (
        f"'module_name' has changed position: {params}"
    )
