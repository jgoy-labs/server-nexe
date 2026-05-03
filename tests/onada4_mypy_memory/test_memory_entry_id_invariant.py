"""Anti-regressió Cluster 4 — `MemoryEntry.id` post-validator invariant.

Cobreix els 7 findings mypy a `flash_memory.py:62, 68`, `persistence.py:195, 202, 212`,
`deduplicator.py:105, 107`. Tots són variants de `Argument has incompatible type
"str | None"; expected "str"`. La causa és el camp pydantic
`MemoryEntry.id: Optional[str] = Field(default=None)` (memory_entry.py:22), que
mypy correctament tipa `Optional[str]` malgrat el `model_validator(mode="after")`
(L70-82) que assigna SHA256(content)[:16] si `not self.id`.

Decisió Director (DUBTE 4): opció B principal — refactor model `id: str =
Field(default="")`. Fallback A — `assert entry.id is not None` als 7 callsites.

CONTRACTE PINAT (compatible amb opció A i B):
1. Després de crear `MemoryEntry(content=...)`, `entry.id` és sempre **str no-buit**.
2. La signatura `model_validator(mode='after').generate_deterministic_id` segueix
   present (premisa del invariant).
3. Re-creant un MemoryEntry amb el mateix content dóna el mateix id (determinisme
   SHA256, premisa del fix opció B amb `default=""` que igualment ha de fer fallback
   al hash si `not self.id`).

Pre-fix (HEAD `30eb2a6`): contracte ja es compleix gràcies al validator after.
Post-fix B: ha de seguir complint-se (default="" + validator). Post-fix A: model
intacte, contracte trivialment OK.
"""

from __future__ import annotations

import inspect


def _make_entry(content: str = "test memory content"):
    from memory.memory.models.memory_entry import MemoryEntry
    from memory.memory.models.memory_types import MemoryType

    return MemoryEntry(content=content, entry_type=MemoryType.EPISODIC)


def test_memory_entry_id_is_non_empty_str_after_creation() -> None:
    """`MemoryEntry(content=...).id` és sempre `str` no-buit (validator garanteix)."""
    entry = _make_entry()
    assert entry.id is not None, (
        "Validator after no ha assignat id — refactor model trencat (opció B fallback A)."
    )
    assert isinstance(entry.id, str), f"id no és str: {type(entry.id).__name__}"
    assert len(entry.id) > 0, "id és buit — validator no genera SHA256."


def test_memory_entry_id_is_deterministic_sha256_prefix() -> None:
    """Pina invariant SHA256(content)[:16] (16 chars hex)."""
    entry_a = _make_entry("identic content for hash check")
    entry_b = _make_entry("identic content for hash check")
    assert entry_a.id == entry_b.id, (
        "id no determinista — validator after canviat o eliminat (cluster 4 trencat)."
    )
    assert len(entry_a.id) == 16, (
        f"id length canviada: {len(entry_a.id)} (esperat 16, SHA256[:16])."
    )
    # 16-char hex (lowercase)
    assert all(c in "0123456789abcdef" for c in entry_a.id), (
        f"id no és hex lowercase: {entry_a.id!r} — validator ha canviat de format."
    )


def test_memory_entry_explicit_id_preserved() -> None:
    """Si el caller passa un id explícit, el validator NO el sobreescriu.

    Aquesta branca és la que el validator usa via `if not self.id` — pinar-la
    evita que un fix opció B amb `default=""` es trenqui silenciosament si
    pydantic v2 tracta `""` igual que None al validator (cas que el Director
    ha demanat verificar empíricament a Dev#2)."""
    from memory.memory.models.memory_entry import MemoryEntry
    from memory.memory.models.memory_types import MemoryType

    entry = MemoryEntry(
        id="custom_id_123",
        content="any content",
        entry_type=MemoryType.EPISODIC,
    )
    assert entry.id == "custom_id_123", (
        "Validator after sobreescriu un id passat explícitament — trenca dedup."
    )


def test_memory_entry_validator_after_present() -> None:
    """Anti-regressió: el `model_validator(mode='after')` que genera l'id segueix definit.

    Si Dev#2 elimina el validator (e.g., pensant que `default=""` és suficient),
    aquest test dispara abans que els tests anteriors, donant un missatge més clar."""
    from memory.memory.models.memory_entry import MemoryEntry

    assert hasattr(MemoryEntry, "generate_deterministic_id"), (
        "Validator `generate_deterministic_id` ha desaparegut — invariant id trencat."
    )
    # El validator és un mètode (decorat per pydantic), assert via inspect que continua
    # essent crida-able.
    assert callable(getattr(MemoryEntry, "generate_deterministic_id"))


def test_memory_entry_id_field_signature_compatible() -> None:
    """Anti-regressió: el camp `id` accepta tant l'opció A (Optional[str]) com B (str
    no-Optional). Pina que `MemoryEntry.__init__` accepta crida amb i sense `id`."""
    from memory.memory.models.memory_entry import MemoryEntry

    sig = inspect.signature(MemoryEntry)
    # MemoryEntry és pydantic; signature mostra els camps com a paràmetres.
    assert "id" in sig.parameters, (
        "Camp `id` ha desaparegut de MemoryEntry — out-of-scope cluster 4."
    )
    assert "content" in sig.parameters
    assert "entry_type" in sig.parameters
