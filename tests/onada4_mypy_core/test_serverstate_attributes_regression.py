"""Anti-regressió cluster `ServerState` atributs dinàmics (Onada 4.1, BUS Dev#1bis).

Cobreix els findings mypy #45, #46, #47, #65 (`01-classificacio.md`). Avui
els 4 atributs (`_cleanup_task`, `_prewarm_task`, `_session_cleanup_task`,
`configure_modules_callback`) NO estan declarats al `ServerState.__init__` —
s'assignen via `setattr` dinàmic a `core/lifespan.py:461,467,512` i
`core/server/factory_state.py:42`. Mypy flagueja `attr-defined`.

El fix Dev#2 (Cluster 1) afegirà aquests 4 atributs al `__init__` amb default
None i anotació Optional. El comportament observable runtime ha de ser
estable: l'assignació dinàmica posterior continua funcionant, i el default
post-fix és None.

Aquest test pina dos contractes runtime estables a través del fix:

1. **Default observable:** `getattr(state, attr, None) is None` — pre-fix és
   None per fallback de getattr (atribut absent), post-fix és None pel default
   declarat. Si Dev#2 inadvertidament inicialitza un atribut a un valor
   no-None (e.g. `self._cleanup_task: Task = asyncio.create_task(...)`), el
   test salta.

2. **Settability runtime:** els 4 atributs són settable via setattr i
   recuperables via getattr (patró exacte de lifespan.py:461 etc). Detecta
   si Dev#2 introduís un descriptor read-only o un `__slots__` restrictiu.

CEC: només instanciació pública de `ServerState` + getattr/setattr. Cap
lectura del cos de `lifespan.py` ni de `factory_state.py`.
"""

from __future__ import annotations

DYNAMIC_ATTRS = (
    "_cleanup_task",
    "_prewarm_task",
    "_session_cleanup_task",
    "configure_modules_callback",
)


def test_serverstate_dynamic_attrs_default_to_none_via_getattr() -> None:
    """Pina contracte: pre i post-fix, `getattr(state, attr, None) is None`.

    Pre-fix: l'atribut no existeix, getattr retorna el fallback None.
    Post-fix: l'atribut existeix a __init__ inicialitzat a None.
    Observable runtime idèntic.
    """
    from core.lifespan import ServerState

    state = ServerState()
    for attr in DYNAMIC_ATTRS:
        assert getattr(state, attr, None) is None, (
            f"ServerState().{attr} (via getattr default=None) = "
            f"{getattr(state, attr, None)!r}, esperat None. "
            f"Si el fix Onada 4.1 inicialitza l'atribut a un valor no-None, "
            f"trenca el contracte runtime amb lifespan.py:461,467,512 + "
            f"factory_state.py:42 (que confien que el default és None abans "
            f"d'assignar via setattr)."
        )


def test_serverstate_dynamic_attrs_are_settable_runtime() -> None:
    """Pina contracte: els 4 atributs es poden assignar via setattr i
    recuperar via getattr (patró exacte de lifespan.py:461 i factory_state.py:42).
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
            f"ServerState().{attr} no és settable runtime — el fix Onada 4.1 "
            f"hauria de mantenir-lo settable (lifespan.py:461 etc l'assigna "
            f"dinàmicament)."
        )


def test_serverstate_known_init_attrs_are_present() -> None:
    """Pina contracte sobre els 9 atributs ja existents al __init__ (firma
    declarada a `core/lifespan.py:185-196` — read-only, no implementació).

    Si Dev#2 elimina algun d'aquests durant el fix de Cluster 1/2, el test
    salta.
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
            f"ServerState ha perdut l'atribut existent `{attr}` — "
            f"refactor col·lateral fora d'abast Onada 4.1."
        )
