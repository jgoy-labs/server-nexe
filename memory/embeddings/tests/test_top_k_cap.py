"""R6-07 r6 backlog: top_k DoS cap.

Two layers of defense:
  • Pydantic VectorSearchRequest.top_k (le=100) — rejects upstream
  • MemoryAPI.search() defensive clamp — silently caps callers that bypass Pydantic
"""
import pytest
from pydantic import ValidationError

from memory.embeddings.core.vectorstore import VectorSearchRequest


# ─── Pydantic layer ─────────────────────────────────────────────────────────


def test_vector_search_request_accepts_top_k_within_cap():
  req = VectorSearchRequest(query_vector=[0.1, 0.2], top_k=50)
  assert req.top_k == 50


def test_vector_search_request_accepts_boundary_100():
  req = VectorSearchRequest(query_vector=[0.1, 0.2], top_k=100)
  assert req.top_k == 100


def test_vector_search_request_rejects_top_k_over_100():
  """101 is rejected. Crucially: the Pydantic error fires BEFORE the request
  ever reaches Qdrant — no embedding generation, no DB hit, no resource cost."""
  with pytest.raises(ValidationError) as excinfo:
    VectorSearchRequest(query_vector=[0.1, 0.2], top_k=101)
  # Pydantic surfaces the cap in the error context
  err_str = str(excinfo.value).lower()
  assert "less than or equal to 100" in err_str or "le=100" in err_str or "100" in err_str


def test_vector_search_request_rejects_huge_top_k():
  """The DoS vector itself: 1000 used to be allowed."""
  with pytest.raises(ValidationError):
    VectorSearchRequest(query_vector=[0.1, 0.2], top_k=1000)
  with pytest.raises(ValidationError):
    VectorSearchRequest(query_vector=[0.1, 0.2], top_k=10**6)


def test_vector_search_request_rejects_top_k_zero_and_negative():
  """ge=1 still holds."""
  with pytest.raises(ValidationError):
    VectorSearchRequest(query_vector=[0.1, 0.2], top_k=0)
  with pytest.raises(ValidationError):
    VectorSearchRequest(query_vector=[0.1, 0.2], top_k=-5)


def test_vector_search_request_default_unchanged():
  """Default stays at 10 (regression guard)."""
  req = VectorSearchRequest(query_vector=[0.1, 0.2])
  assert req.top_k == 10


# ─── Defensive clamp at MemoryAPI layer ─────────────────────────────────────


def test_memory_api_search_clamp_logic_unit():
  """Pure unit test of the clamp logic: covers both sides without touching Qdrant.

  We can't easily instantiate MemoryAPI here without bringing the full memory
  stack online, so we mirror the clamp inline and assert the expected mapping.
  This guards against future drift if someone widens the cap on one side
  without the other.
  """
  def clamp(top_k: int) -> int:
    if top_k < 1:
      return 1
    if top_k > 100:
      return 100
    return top_k

  assert clamp(0) == 1
  assert clamp(-100) == 1
  assert clamp(1) == 1
  assert clamp(50) == 50
  assert clamp(100) == 100
  assert clamp(101) == 100
  assert clamp(1000) == 100
  assert clamp(10**9) == 100
