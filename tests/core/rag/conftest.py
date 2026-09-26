"""Reset the RAG source registry around every test in this package.

The registry (`core/rag/registry.py`, ADR-008 E1b) is global mutable state.
Without this, a test that registers a source and does not remove it changes
what the NEXT test's turn retrieves — the failure mode being a test that
passes alone and fails in a suite, or the reverse, which is worse because it
looks like flakiness.

Autouse and around (not just after): a leak from somewhere else should not be
able to make a test here pass for the wrong reason either.
"""

import pytest

from core.rag.registry import clear_registered_sources


@pytest.fixture(autouse=True)
def _clean_rag_registry():
    clear_registered_sources()
    yield
    clear_registered_sources()
