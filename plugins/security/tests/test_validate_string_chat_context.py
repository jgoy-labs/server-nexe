"""
────────────────────────────────────
Server Nexe
Location: plugins/security/tests/test_validate_string_chat_context.py
Description: Ensure validate_string_input(context="chat") skips detectors
that produce false positives when users legitimately discuss code or SQL.
────────────────────────────────────

Rationale
---------
The chat pipeline used to trip on perfectly legal natural language — the
ellipsis "vei..." was flagged as path traversal, a sentence like "the
admin ran DROP TABLE logs last week" was flagged as SQL injection. These
detectors are valuable on structured params, session IDs and file names,
but not on free-form conversation.

context="chat" therefore disables the four highest-false-positive
detectors: command, LDAP, path_traversal, and SQL. XSS still fires
because rendered chat responses can reach the browser.

context="param" (the default) behaves as before: all detectors active.
"""

import pytest
from fastapi import HTTPException

from plugins.security.core.input_sanitizers import validate_string_input


# Sentence matches the real SQL detector pattern
# r'\b(union|select|...)\b.*\bfrom\b' — legitimate in a technical
# conversation about SQL but currently rejected in chat.
SQL_LIKE_CHAT = "Can you explain UNION SELECT * FROM logs to a beginner?"


def test_chat_context_allows_sql_like_discussion() -> None:
  """Natural-language mention of SQL keywords must not be blocked in chat."""
  out = validate_string_input(SQL_LIKE_CHAT, context="chat")
  assert "UNION SELECT" in out


def test_chat_context_allows_command_metacharacters() -> None:
  """`cat file.txt | grep foo` is valid tech talk in chat."""
  out = validate_string_input("I ran `cat file.txt | grep foo`.", context="chat")
  assert "grep" in out


def test_chat_context_allows_ellipsis_and_paths() -> None:
  """Ellipsis ("...") and path-like strings must not trigger in chat."""
  out = validate_string_input("See the etc directory, for example /etc/...", context="chat")
  assert "/etc/" in out


def test_chat_context_still_blocks_xss() -> None:
  """XSS stays blocked in chat: rendered output can reach the browser."""
  with pytest.raises(HTTPException) as exc_info:
    validate_string_input("<script>alert(1)</script>", context="chat")
  assert exc_info.value.status_code == 400


def test_param_context_still_blocks_sql() -> None:
  """Default context (param) keeps SQL detection active — regression guard."""
  with pytest.raises(HTTPException) as exc_info:
    validate_string_input("1' UNION SELECT * FROM users--", context="param")
  assert exc_info.value.status_code == 400


def test_param_context_still_blocks_command_injection() -> None:
  """Default context (param) keeps command-injection detection active."""
  with pytest.raises(HTTPException) as exc_info:
    validate_string_input("file.txt; rm -rf /", context="param")
  assert exc_info.value.status_code == 400


def test_param_context_still_blocks_path_traversal() -> None:
  """Default context (param) keeps path-traversal detection active."""
  with pytest.raises(HTTPException) as exc_info:
    validate_string_input("../../etc/passwd", context="param")
  assert exc_info.value.status_code == 400


def test_explicit_check_sql_false_in_param_context() -> None:
  """Callers can still override per-detector flags for bespoke cases."""
  out = validate_string_input("DROP TABLE users", context="param", check_sql=False)
  assert "DROP TABLE users" in out
