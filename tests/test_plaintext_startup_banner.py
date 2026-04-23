"""
────────────────────────────────────
Server Nexe
Location: tests/test_plaintext_startup_banner.py
Description: Verify the plaintext-mode startup banner is loud enough that
operators will notice encryption at rest is DISABLED.
────────────────────────────────────

Before this fix, the WARNING was a single soft log line
("Encryption not available (sqlcipher3 not installed). Data stored in
plain text. Set NEXE_ENCRYPTION_ENABLED=false to suppress this warning.")
that got buried in startup logs. The factory here produces a multi-line
banner that calls out the security impact, the remediation commands, and
how to silence the notice — all at a glance.
"""

from core.crypto import format_plaintext_startup_banner


def test_banner_signals_encryption_is_disabled() -> None:
  banner = format_plaintext_startup_banner()
  upper = banner.upper()
  assert "PLAINTEXT" in upper
  assert "DISABLED" in upper or "NOT" in upper  # "DISABLED" or "NOT installed"


def test_banner_includes_fail_closed_remediation() -> None:
  """The operator must be told how to require encryption."""
  banner = format_plaintext_startup_banner()
  assert "NEXE_ENCRYPTION_ENABLED=true" in banner
  assert "sqlcipher3" in banner


def test_banner_includes_suppression_hint() -> None:
  """The operator must be told how to silence the notice for dev/CI."""
  banner = format_plaintext_startup_banner()
  assert "NEXE_ENCRYPTION_ENABLED=false" in banner


def test_banner_is_multiline_visual() -> None:
  """Banner is multi-line and uses a visual separator so it stands out.

  Single-line warnings get lost in verbose startup logs; multi-line +
  separator gives the eye something to lock onto.
  """
  banner = format_plaintext_startup_banner()
  assert banner.count("\n") >= 4, "banner should span several lines"
  # Accept any separator character repeated — ═ (current), = or ─ are fine.
  assert any(sep * 20 in banner for sep in ("═", "=", "─", "-", "#")), (
    "banner should include a visual separator line"
  )


def test_banner_mentions_what_is_plaintext() -> None:
  """Operator should see which data is affected (memory, sessions, RAG)."""
  banner = format_plaintext_startup_banner().lower()
  affected_hints = ("memor", "session", "rag", "data")
  assert any(h in banner for h in affected_hints), (
    "banner should list at least one affected data category"
  )
