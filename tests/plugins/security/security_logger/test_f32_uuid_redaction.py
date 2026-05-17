"""
F3.2 BUG-NB-6 — `redact_api_key` must also catch UUID-shaped keys (8-4-4-4-12 hex).
"""
from __future__ import annotations

from plugins.security.security_logger.sanitizers import redact_api_key


class TestUuidShapedKeyRedaction:
    def test_uuid_v4_redacted(self):
        key = "a1b2c3d4-e5f6-7890-1234-567890abcdef"
        out = redact_api_key(f"prefix {key} suffix")
        assert key not in out
        assert "[REDACTED_API_KEY]" in out

    def test_uuid_uppercase_redacted(self):
        key = "A1B2C3D4-E5F6-7890-1234-567890ABCDEF"
        out = redact_api_key(key)
        assert "[REDACTED_API_KEY]" in out
        assert key not in out

    def test_legacy_hex_run_still_redacted(self):
        # The pre-existing hex >= 32 chars rule must still fire.
        hex_key = "a" * 64  # 64-char hex string
        out = redact_api_key(f"token={hex_key};")
        assert "[REDACTED_API_KEY]" in out
        assert hex_key not in out

    def test_short_hex_not_redacted(self):
        # 8 hex chars (without hyphens) is below the threshold and not UUID-shaped.
        out = redact_api_key("commit a1b2c3d4 landed")
        assert "a1b2c3d4" in out

    def test_no_key_passthrough(self):
        msg = "Plain log line with no secrets."
        assert redact_api_key(msg) == msg
