"""Anti-regressió Cluster 6 — `RAGCLI.module` post-init guard.

Cobreix els 5 findings mypy `union-attr` a `memory/rag/cli.py:59, 108, 185, 217, 229`.
Tots són `Item "None" of "RAGModule | None" has no attribute X` perquè
`self.module: Optional[RAGModule] = None` (cli.py:31) i `cmd_*` cridats abans
d'`initialize()` accedeixen `self.module.X()` directament.

Decisió Director (Cluster 6): Dev#2 introdueix helper `_require_module(self) -> RAGModule`
que llança `RuntimeError("RAG not initialized")` i substitueix `self.module.X()` per
`self._require_module().X()` als 5 callsites.

CONTRACTE PINAT:
1. `RAGCLI()` post-construcció té `self.module is None` (premisa del bug).
2. `cmd_info`, `cmd_health`, `cmd_search`, `cmd_sources` són `async def`
   (ja que tots usen `await` o esperen mòdul async). Fix Cluster 6 NO ha de canviar
   les seves signatures externes.
3. Cridats sense initialize, retornen `1` (graceful failure via try/except global)
   en lloc de propagar excepció. Aquest contracte es compleix pre i post-fix:
   pre-fix `AttributeError` → except → return 1; post-fix `RuntimeError` → except → return 1.

Pre-fix (HEAD `30eb2a6`): contracte runtime es compleix gràcies al try/except.
Post-fix: ha de seguir complint-se. Si Dev#2 elimina el try/except (out-of-scope),
la suite detecta la regressió.
"""

from __future__ import annotations

import asyncio
import inspect

import pytest


def test_ragcli_module_optional_at_init() -> None:
    """`RAGCLI()` ha de tenir `self.module is None` post-construcció.

    Aquest test pina la premisa del cluster: el camp existeix com a `Optional` i
    comença a None. Si Dev#2 canvia el tipus o el valor inicial (e.g., a una
    instància dummy), trenca la condició del bug i invalida el helper proposat."""
    from memory.rag.cli import RAGCLI

    cli = RAGCLI()
    assert cli.module is None, (
        "RAGCLI.__init__ ja no inicialitza module a None — premisa cluster 6 trencada."
    )


def test_ragcli_async_methods_signatures_pinned() -> None:
    """Pina que els 4 mètodes `cmd_*` afectats segueixen sent async i prenen `args`.

    Els findings mypy són a cli.py:59 (cmd_info), 108 (cmd_health), 185 (cmd_search),
    217 + 229 (cmd_sources). Si Dev#2 canvia signatures (e.g. afegint `module: RAGModule`
    com a paràmetre per evitar el guard), trenca tots els callers via `argparse`."""
    from memory.rag.cli import RAGCLI

    for method_name in ("cmd_info", "cmd_health", "cmd_search", "cmd_sources"):
        method = getattr(RAGCLI, method_name, None)
        assert method is not None, f"RAGCLI.{method_name} ha desaparegut."
        assert inspect.iscoroutinefunction(method), (
            f"RAGCLI.{method_name} ha perdut `async def` — out-of-scope cluster 6."
        )
        sig = inspect.signature(method)
        # `self` + `args`
        assert len(sig.parameters) == 2, (
            f"Signatura RAGCLI.{method_name}{sig} ha canviat — esperat (self, args)."
        )


def test_ragcli_cmd_info_returns_one_without_initialize() -> None:
    """Anti-regressió comportament: `cmd_info` cridat sense `initialize()`
    completa amb return 1 (no propaga excepció a fora).

    Pre-fix: AttributeError caçat per try/except → return 1.
    Post-fix: RuntimeError caçat per try/except → return 1.
    Si Dev#2 elimina el try/except global de cmd_info, el test FALLA."""
    from memory.rag.cli import RAGCLI

    cli = RAGCLI()
    assert cli.module is None  # precondició

    # cmd_info pren `args` però no l'usa, podem passar None
    rc = asyncio.run(cli.cmd_info(args=None))
    assert rc == 1, (
        f"cmd_info sense initialize ha retornat {rc} (esperat 1). "
        "El try/except global ha estat eliminat o el helper post-fix propaga."
    )


def test_ragcli_cmd_health_returns_one_without_initialize() -> None:
    """Idèntic anti-regressió per cmd_health."""
    from memory.rag.cli import RAGCLI

    cli = RAGCLI()
    rc = asyncio.run(cli.cmd_health(args=None))
    assert rc == 1
