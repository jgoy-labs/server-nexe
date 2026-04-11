"""Tests for P1-4 upload content denylist (speed-bump, not security).

Tests the extracted helper `_detect_sensitive_upload()` directly —
same strategy as P0-2.c (_check_llama_cpp_available) because slowapi's
@limiter.limit rejects MagicMock on the full endpoint.
"""
import pytest

try:
  from plugins.web_ui_module.api.routes_files import (
    _detect_sensitive_upload,
    _SENSITIVE_UPLOAD_SCAN_LIMIT,
  )
except ImportError:
  pytest.skip("_detect_sensitive_upload helper not available", allow_module_level=True)


# ─── Positive: should be rejected ──────────────────────────────────────────

def test_reject_passwd_header():
  """/etc/passwd first line must be detected."""
  content = b"root:x:0:0:root:/root:/bin/bash\nuser:x:1000:1000::/home/user:/bin/zsh"
  matched = _detect_sensitive_upload(content)
  assert matched == b"root:x:0:0:"


def test_reject_ssh_rsa_private_key():
  """OpenSSH/RSA private key PEM header must be detected."""
  content = b"-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA...\n-----END RSA PRIVATE KEY-----"
  matched = _detect_sensitive_upload(content)
  assert matched == b"-----BEGIN RSA PRIVATE KEY-----"


def test_reject_openssh_private_key():
  """OpenSSH-format private key must be detected."""
  content = b"-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXkt...\n"
  matched = _detect_sensitive_upload(content)
  assert matched == b"-----BEGIN OPENSSH PRIVATE KEY-----"


def test_reject_pgp_private_key():
  """GPG/PGP private key export must be detected (bonus pattern)."""
  content = b"-----BEGIN PGP PRIVATE KEY BLOCK-----\nlQOYBGNyz2oBCADA...\n"
  matched = _detect_sensitive_upload(content)
  assert matched == b"-----BEGIN PGP PRIVATE KEY BLOCK-----"


def test_reject_anthropic_api_key():
  """Anthropic Claude API key (sk-ant-) in env file or script must be detected."""
  content = b"ANTHROPIC_API_KEY=sk-ant-api03-abcdef123456789_xxxxxxxxxxxxxxxx\n"
  matched = _detect_sensitive_upload(content)
  assert matched == b"sk-ant-"


def test_reject_openai_project_key():
  """OpenAI project key (sk-proj-) — covers GPT, Codex CLI, Responses API."""
  content = b"OPENAI_API_KEY=sk-proj-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx\n"
  matched = _detect_sensitive_upload(content)
  assert matched == b"sk-proj-"


def test_reject_github_pat_classic():
  """GitHub PAT classic format (ghp_)."""
  content = b"GH_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx\n"
  matched = _detect_sensitive_upload(content)
  assert matched == b"ghp_"


def test_reject_github_pat_fine_grained():
  """GitHub fine-grained PAT (github_pat_)."""
  content = b"GITHUB_TOKEN=github_pat_11ABCDEFG_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx\n"
  matched = _detect_sensitive_upload(content)
  assert matched == b"github_pat_"


def test_reject_google_gemini_api_key():
  """Google API key (AIzaSy) — covers Gemini, AI Studio, Cloud, Firebase."""
  content = b"GOOGLE_API_KEY=AIzaSyBfT0AbCdEfGhIjKlMnOpQrStUvWxYz12345\n"
  matched = _detect_sensitive_upload(content)
  assert matched == b"AIzaSy"


# ─── Negative: should be accepted ──────────────────────────────────────────

def test_accept_legitimate_pdf_header():
  """A real PDF file should not match any pattern."""
  content = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj"
  assert _detect_sensitive_upload(content) is None


def test_accept_text_with_passwd_word_inline():
  """Text mentioning 'passwd' as a word (not the file format) must pass."""
  content = b"Remember to change your passwd after first login. See man page for details."
  assert _detect_sensitive_upload(content) is None


def test_accept_plain_text_document():
  """Normal markdown / text content passes."""
  content = b"# My Document\n\nThis is a regular text file with some content.\n"
  assert _detect_sensitive_upload(content) is None


def test_accept_text_mentioning_sk_prefix_without_full_match():
  """Talking about 'sk-' prefix as a concept must NOT trigger the detector.

  The patterns are `sk-ant-` and `sk-proj-` specifically; a bare mention of
  "sk-" (used in docs/tutorials when discussing API key formats) does not match.
  """
  content = b"API keys usually start with sk- followed by the provider code"
  assert _detect_sensitive_upload(content) is None


def test_accept_text_mentioning_github_as_word():
  """Talking about 'github' as a word must NOT trigger (no ghp_ / github_pat_)."""
  content = b"The github repository is at https://github.com/org/repo"
  assert _detect_sensitive_upload(content) is None


# ─── Edge cases ────────────────────────────────────────────────────────────

def test_empty_content_returns_none():
  """Empty upload returns None (nothing to scan)."""
  assert _detect_sensitive_upload(b"") is None


def test_none_like_returns_none():
  """Defensive: empty bytes handled gracefully."""
  assert _detect_sensitive_upload(bytes()) is None


def test_scan_limited_to_first_8kb():
  """Design decision: the scan window is limited to the first 8KB.

  Patterns appearing AFTER byte 8192 are NOT detected. This is
  intentional (performance tradeoff for a speed-bump that's already
  bypassable by any competent attacker). A future dev MUST NOT remove
  this limit without understanding the tradeoff.
  """
  # 10KB of harmless padding + sensitive pattern at position 10000
  padding = b"A" * 10000
  content = padding + b"-----BEGIN RSA PRIVATE KEY-----\n"

  # Sanity: content is actually > 8KB
  assert len(content) > _SENSITIVE_UPLOAD_SCAN_LIMIT

  # The pattern is past the scan window, so detection is None
  matched = _detect_sensitive_upload(content)
  assert matched is None, (
    "Design decision v0.9.1 P1-4: scan limited to first 8KB. "
    "Patterns after byte 8192 are NOT caught. If this assertion fails "
    "because the limit was raised, ensure the tradeoff was explicitly "
    "revisited and documented — don't 'fix' it without context."
  )


def test_pattern_cut_at_8kb_boundary_is_missed():
  """Edge case limitation: pattern cut off at the 8KB boundary is NOT detected.

  `bytes.__contains__` requires a complete substring match. If a pattern's
  start is within the scan window but its end extends past byte 8192, the
  scan returns None because only a prefix of the pattern lives in head[:8192].

  This is an accepted limitation of the speed-bump design:
  - Documented here so a future dev doesn't get confused by the behavior
  - NOT mitigated (would require scanning an extra buffer window, which
    adds cost for marginal coverage improvement against an already
    trivially-bypassable filter)

  A determined attacker who wants to evade this has a thousand easier
  options than padding exactly to byte 8172. The speed-bump is aimed at
  accidents, not adversaries.
  """
  prefix = b"X" * (_SENSITIVE_UPLOAD_SCAN_LIMIT - 20)  # 20 bytes of the 31-byte pattern fit
  content = prefix + b"-----BEGIN RSA PRIVATE KEY-----\n"

  # Only the first 20 bytes of the pattern are in head[:8192], not the full 31
  matched = _detect_sensitive_upload(content)
  assert matched is None, (
    "Pattern cut at the 8KB boundary is not detected (bytes.__contains__ "
    "requires complete match). This is documented behavior, not a bug."
  )


def test_pattern_fully_within_8kb_window_detected():
  """Pattern entirely within head[:8192] IS detected (happy path for boundary)."""
  # Leave room for the full 31-byte pattern inside the scan window
  prefix = b"X" * (_SENSITIVE_UPLOAD_SCAN_LIMIT - 100)  # 100 bytes of padding remaining
  content = prefix + b"-----BEGIN RSA PRIVATE KEY-----\n"

  matched = _detect_sensitive_upload(content)
  assert matched == b"-----BEGIN RSA PRIVATE KEY-----"
