"""#888 — the vector width lives in core, and must not drift from memory/.

``core/endpoints/chat_memory.py`` is reached at import time from
``create_app()``. When it imported ``memory.memory.constants`` the whole
memory package (MemoryModule, MemoryAPI, embeddings) came with it, so a broken
memory/ meant NO server at all — not even /health or /ui. The constant now
lives in ``core.memory_access``.

Moving a value out of its home package buys resilience and costs a second
source of truth. That is only acceptable while something fails when the two
disagree — this test is that something. Same reasoning as the duplicated
``_EMBEDDER_MODEL_ID`` in core/endpoints/installer.py, which has no anchor yet.
"""
from __future__ import annotations

from core.memory_access import DEFAULT_VECTOR_SIZE as CORE_VECTOR_SIZE


def test_core_vector_size_matches_the_embeddings_declaration():
    """core's copy == the canonical declaration in memory/embeddings."""
    from memory.embeddings.constants import DEFAULT_VECTOR_SIZE as CANONICAL

    assert CORE_VECTOR_SIZE == CANONICAL, (
        "core.memory_access.DEFAULT_VECTOR_SIZE "
        f"({CORE_VECTOR_SIZE}) has drifted from the canonical "
        f"memory/embeddings/constants.py ({CANONICAL}). Collections would be "
        "created with the wrong width. Update core/memory_access.py."
    )


def test_core_vector_size_matches_the_memory_re_export():
    """The re-export memory/ uses internally must agree too."""
    from memory.memory.constants import DEFAULT_VECTOR_SIZE as RE_EXPORT

    assert CORE_VECTOR_SIZE == RE_EXPORT, (
        f"core ({CORE_VECTOR_SIZE}) != memory.memory.constants ({RE_EXPORT})"
    )


def test_chat_memory_does_not_import_memory_at_module_level():
    """The import that broke create_app() must not come back (#888).

    Textual check on purpose: by the time this test runs the module is already
    imported, so asserting on the loaded object would pass either way.
    """
    from pathlib import Path

    src = (Path(__file__).resolve().parents[2]
           / "core" / "endpoints" / "chat_memory.py").read_text()
    module_level = [
        line for line in src.splitlines()
        if line.startswith(("from memory", "import memory"))
    ]
    assert not module_level, (
        "core/endpoints/chat_memory.py imports memory/ at module level again: "
        f"{module_level}. create_app() is reached through this file — see "
        "tests/core/test_g1_memory_degradation.py"
    )
