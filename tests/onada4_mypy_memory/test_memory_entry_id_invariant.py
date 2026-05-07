"""Anti-regression Cluster 4 — `MemoryEntry.id` post-validator invariant.

Covers the 7 mypy findings at `flash_memory.py:62, 68`, `persistence.py:195, 202, 212`,
`deduplicator.py:105, 107`. All are variants of `Argument has incompatible type
"str | None"; expected "str"`. The cause is the pydantic field
`MemoryEntry.id: Optional[str] = Field(default=None)` (memory_entry.py:22), which
mypy correctly types as `Optional[str]` despite the `model_validator(mode="after")`
(L70-82) that assigns SHA256(content)[:16] if `not self.id`.

Director decision (DUBTE 4): main option B — refactor model `id: str =
Field(default="")`. Fallback A — `assert entry.id is not None` at the 7 callsites.

PINNED CONTRACT (compatible with option A and B):
1. After creating `MemoryEntry(content=...)`, `entry.id` is always a **non-empty str**.
2. The signature `model_validator(mode='after').generate_deterministic_id` remains
   present (premise of the invariant).
3. Re-creating a MemoryEntry with the same content gives the same id (SHA256
   determinism, premise of option B fix with `default=""` which must likewise fall back
   to the hash if `not self.id`).

Pre-fix (HEAD `30eb2a6`): contract is already fulfilled thanks to the after validator.
Post-fix B: must continue to be fulfilled (default="" + validator). Post-fix A: model
intact, contract trivially OK.
"""

from __future__ import annotations

import inspect


def _make_entry(content: str = "test memory content"):
    from memory.memory.models.memory_entry import MemoryEntry
    from memory.memory.models.memory_types import MemoryType

    return MemoryEntry(content=content, entry_type=MemoryType.EPISODIC)


def test_memory_entry_id_is_non_empty_str_after_creation() -> None:
    """`MemoryEntry(content=...).id` is always a non-empty `str` (validator guarantees)."""
    entry = _make_entry()
    assert entry.id is not None, (
        "After validator did not assign id — model refactor broken (option B fallback A)."
    )
    assert isinstance(entry.id, str), f"id is not str: {type(entry.id).__name__}"
    assert len(entry.id) > 0, "id is empty — validator does not generate SHA256."


def test_memory_entry_id_is_deterministic_sha256_prefix() -> None:
    """Pins SHA256(content)[:16] invariant (16 hex chars)."""
    entry_a = _make_entry("identic content for hash check")
    entry_b = _make_entry("identic content for hash check")
    assert entry_a.id == entry_b.id, (
        "id is not deterministic — after validator changed or removed (cluster 4 broken)."
    )
    assert len(entry_a.id) == 16, (
        f"id length changed: {len(entry_a.id)} (expected 16, SHA256[:16])."
    )
    # 16-char hex (lowercase)
    assert all(c in "0123456789abcdef" for c in entry_a.id), (
        f"id is not lowercase hex: {entry_a.id!r} — validator has changed format."
    )


def test_memory_entry_explicit_id_preserved() -> None:
    """If the caller passes an explicit id, the validator does NOT overwrite it.

    This branch is the one the validator uses via `if not self.id` — pinning it
    prevents an option B fix with `default=""` from breaking silently if
    pydantic v2 treats `""` the same as None in the validator (a case the Director
    has asked Dev#2 to verify empirically)."""
    from memory.memory.models.memory_entry import MemoryEntry
    from memory.memory.models.memory_types import MemoryType

    entry = MemoryEntry(
        id="custom_id_123",
        content="any content",
        entry_type=MemoryType.EPISODIC,
    )
    assert entry.id == "custom_id_123", (
        "After validator overwrites an explicitly passed id — breaks dedup."
    )


def test_memory_entry_validator_after_present() -> None:
    """Anti-regression: the `model_validator(mode='after')` that generates the id remains defined.

    If Dev#2 removes the validator (e.g., thinking `default=""` is sufficient),
    this test fires before the previous ones, giving a clearer message."""
    from memory.memory.models.memory_entry import MemoryEntry

    assert hasattr(MemoryEntry, "generate_deterministic_id"), (
        "Validator `generate_deterministic_id` has disappeared — id invariant broken."
    )
    # The validator is a method (decorated by pydantic), assert via inspect that it remains
    # callable.
    assert callable(getattr(MemoryEntry, "generate_deterministic_id"))


def test_memory_entry_id_field_signature_compatible() -> None:
    """Anti-regression: the `id` field accepts both option A (Optional[str]) and B (str
    non-Optional). Pins that `MemoryEntry.__init__` accepts calls with and without `id`."""
    from memory.memory.models.memory_entry import MemoryEntry

    sig = inspect.signature(MemoryEntry)
    # MemoryEntry is pydantic; signature shows fields as parameters.
    assert "id" in sig.parameters, (
        "Field `id` has disappeared from MemoryEntry — out-of-scope cluster 4."
    )
    assert "content" in sig.parameters
    assert "entry_type" in sig.parameters
