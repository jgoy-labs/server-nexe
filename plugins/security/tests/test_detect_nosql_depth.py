"""
────────────────────────────────────
Server Nexe
Location: plugins/security/tests/test_detect_nosql_depth.py
Description: Tests for bounded recursion in detect_nosql_injection.
────────────────────────────────────

Before the fix, deeply-nested JSON caused RecursionError (DoS via stack
overflow). After the fix, inputs exceeding MAX_DEPTH are flagged as
suspicious (return True) without recursion explosion.
"""

import pytest

from plugins.security.core.injection_detectors import (
  MAX_NOSQL_DEPTH,
  detect_nosql_injection,
)


def _nested_dict(depth: int, leaf: object = "ok") -> dict:
  node: object = leaf
  for _ in range(depth):
    node = {"a": node}
  return node  # type: ignore[return-value]


def _nested_list(depth: int, leaf: object = "ok") -> list:
  node: object = leaf
  for _ in range(depth):
    node = [node]
  return node  # type: ignore[return-value]


def test_nosql_detector_module_constant_exists() -> None:
  """Public module constant so callers can tune per-endpoint if needed."""
  assert isinstance(MAX_NOSQL_DEPTH, int)
  assert MAX_NOSQL_DEPTH >= 20


def test_shallow_dict_still_works() -> None:
  """Regression: baseline depth-1 dict is unchanged (defense-in-depth fix)."""
  assert detect_nosql_injection({"user": "john"}) is False
  assert detect_nosql_injection({"$where": "x"}) is True


def test_deeply_nested_dict_beyond_max_depth_flags_true() -> None:
  """Dict nested deeper than MAX_NOSQL_DEPTH is flagged suspicious.

  Rationale: legitimate API payloads never nest hundreds of levels.
  Anything that does is either malicious (DoS attempt) or broken; in
  either case the safe default is to reject, not to crash the process.
  """
  payload = _nested_dict(MAX_NOSQL_DEPTH + 50)
  assert detect_nosql_injection(payload) is True


def test_deeply_nested_list_beyond_max_depth_flags_true() -> None:
  """List nested deeper than MAX_NOSQL_DEPTH is also flagged."""
  payload = _nested_list(MAX_NOSQL_DEPTH + 50)
  assert detect_nosql_injection(payload) is True


def test_mixed_dict_list_nesting_beyond_max_depth_flags_true() -> None:
  """Alternating dict/list nesting is still bounded."""
  node: object = "ok"
  for i in range(MAX_NOSQL_DEPTH + 50):
    node = {"k": node} if i % 2 == 0 else [node]
  assert detect_nosql_injection(node) is True


def test_just_under_max_depth_returns_false_for_clean_data() -> None:
  """A nested-but-clean payload just under the cap is NOT flagged."""
  payload = _nested_dict(MAX_NOSQL_DEPTH - 1, leaf="clean_value")
  assert detect_nosql_injection(payload) is False


def test_depth_limit_does_not_mask_real_malicious_at_top_level() -> None:
  """If the top-level already has a $-prefixed key, we return True on
  the first iteration — depth guard never fires, detector still works."""
  payload = {"$where": "function(){return true}"}
  assert detect_nosql_injection(payload) is True


def test_non_recursive_inputs_unchanged() -> None:
  """Primitive types: behaviour identical to pre-fix."""
  assert detect_nosql_injection(42) is False
  assert detect_nosql_injection(True) is False
  assert detect_nosql_injection("") is False
  assert detect_nosql_injection("db.users.find()") is True


def test_does_not_raise_recursion_error_on_pathological_input() -> None:
  """The fix's whole point: pathological input never reaches Python's
  recursion limit. If this test raises RecursionError, the fix regressed.
  """
  payload = _nested_dict(2000)
  try:
    result = detect_nosql_injection(payload)
  except RecursionError:
    pytest.fail("detect_nosql_injection raised RecursionError on 2000-level dict")
  assert result is True
