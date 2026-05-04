"""
Cluster 3 (L331) — path_discovery.find_module_path signatura Optional[Path].

La signatura actual declara -> Path, però el cos retorna modules.get(module_name)
que és Path | None. El docstring ja confirma "Module path or None".

Contract pin: find_module_path('mòdul_inexistent') retorna None sense crash.
El fix mypy (canviar -> Path a -> Optional[Path]) NO ha de trencar aquest contracte.
"""
from pathlib import Path


def test_cluster3_find_module_path_inexistent_returns_none():
    """Anti-regressió: find_module_path amb mòdul inexistent retorna None, no crash.

    PASSA pre-fix (comportament runtime ja correcte).
    FALLA si Dev#2 canvia l'impl. a raise o retorn no-None per a mòduls desconeguts.
    """
    from personality.module_manager.path_discovery import PathDiscovery

    pd = PathDiscovery()
    result = pd.find_module_path("__module_that_does_not_exist_onada4__")

    assert result is None, (
        f"find_module_path retorna {result!r} en lloc de None — "
        "contracte Optional[Path] trencat (Cluster 3 Onada 4.3)"
    )


def test_cluster3_find_module_path_signature_accepts_str():
    """Anti-regressió: find_module_path accepta un str com a únic argument posicional.

    Pina que la signatura pública no afegeixi paràmetres obligatoris nous (Dev#2 scope mypy).
    """
    import inspect
    from personality.module_manager.path_discovery import PathDiscovery

    sig = inspect.signature(PathDiscovery.find_module_path)
    params = list(sig.parameters.keys())

    assert "module_name" in params, (
        f"Paràmetre 'module_name' ha desaparegut de find_module_path — signatura trencada. "
        f"Paràmetres actuals: {params}"
    )
    assert params[1] == "module_name", (
        f"'module_name' ha canviat de posició: {params}"
    )
