"""#888 — the vector width lives in core, and must not drift from memory/.

``create_app()`` used to reach ``core/endpoints/chat_memory.py`` at import
time. When that file imported ``memory.memory.constants`` the whole memory
package (MemoryModule, MemoryAPI, embeddings) came with it, so a broken
memory/ meant NO server at all — not even /health or /ui. The constant now
lives in ``core.memory_access``. The autosave module is gone (F-A); the
constant stays in core so a broken memory/ still cannot take down the
server. ``tests/core/test_g1_memory_degradation.py`` is the runtime gate.

Moving a value out of its home package buys resilience and costs a second
source of truth. That is only acceptable while something fails when the two
disagree — this test is that something. Same reasoning as the duplicated
``_EMBEDDER_MODEL_ID`` in core/endpoints/installer.py, anchored below
(g13, 23/08/2026).
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


def test_installer_embedder_model_matches_the_embeddings_declaration():
    """g13 — the installer's copy == the canonical declaration in memory/embeddings.

    core/endpoints/installer.py keeps its own copy of the fastembed model id on
    purpose: it must stay import-safe inside PBS bundles, where the
    memory/structlog import chain can fail. That copy is NOT to be replaced by an
    import — the resilience is the point.

    What the copy costs is a second source of truth, and the deal only holds
    while something breaks when the two disagree. This test is that something:
    change either side alone and the wizard would install a different model from
    the one memory/ indexes with, producing vectors nothing can search.
    """
    from core.endpoints.installer import _EMBEDDER_MODEL_ID
    from memory.embeddings.constants import DEFAULT_EMBEDDING_MODEL as CANONICAL

    assert _EMBEDDER_MODEL_ID == CANONICAL, (
        f"core/endpoints/installer.py::_EMBEDDER_MODEL_ID ({_EMBEDDER_MODEL_ID!r}) "
        f"has drifted from the canonical memory/embeddings/constants.py::"
        f"DEFAULT_EMBEDDING_MODEL ({CANONICAL!r}). The wizard would install a model "
        f"the rest of the system does not use. Update core/endpoints/installer.py — "
        f"do NOT import the constant: the installer must stay import-safe in PBS bundles."
    )
