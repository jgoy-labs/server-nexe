"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: plugins/security_logger/tests/test_sanitizers.py
Description: Nexe Server Component

www.jgoy.net
────────────────────────────────────
"""

import pytest
from plugins.security_logger.sanitizers import (
  obfuscate_ip,
  redact_api_key,
  truncate_prompt,
  anonymize_path,
  sanitize_log_entry,
)

class TestObfuscateIP:
  """Tests for IP obfuscation (GDPR compliance)."""

  def test_obfuscate_ipv4(self):
    """IPv4 addresses should have last octet masked."""
    assert obfuscate_ip("192.168.1.42") == "192.168.1.xxx"
    assert obfuscate_ip("10.0.0.1") == "10.0.0.xxx"
    assert obfuscate_ip("8.8.8.8") == "8.8.8.xxx"

  def test_localhost_not_obfuscated(self):
    """Localhost addresses should NOT be obfuscated."""
    assert obfuscate_ip("127.0.0.1") == "127.0.0.1"
    assert obfuscate_ip("127.0.0.42") == "127.0.0.42"
    assert obfuscate_ip("::1") == "::1"
    assert obfuscate_ip("localhost") == "localhost"

  def test_empty_and_unknown(self):
    """Empty and unknown values should pass through."""
    assert obfuscate_ip("") == ""
    assert obfuscate_ip("unknown") == "unknown"
    assert obfuscate_ip(None) is None

  def test_non_ipv4_passthrough(self):
    """Non-IPv4 formats should pass through unchanged."""
    assert obfuscate_ip("not-an-ip") == "not-an-ip"
    assert obfuscate_ip("192.168.1") == "192.168.1"

class TestRedactAPIKey:
  """Tests for API key redaction."""

  def test_redact_hex_key_32_chars(self):
    """32-char hex keys should be redacted."""
    text = "Key: 0123456789abcdef0123456789abcdef"
    result = redact_api_key(text)
    assert "[REDACTED_API_KEY]" in result
    assert "0123456789abcdef" not in result

  def test_redact_hex_key_64_chars(self):
    """64-char hex keys should be redacted."""
    key = "a" * 64
    text = f"API: {key}"
    result = redact_api_key(text)
    assert "[REDACTED_API_KEY]" in result
    assert key not in result

  def test_short_hex_not_redacted(self):
    """Hex strings shorter than 32 chars should NOT be redacted."""
    text = "Short: 0123456789abcdef"
    result = redact_api_key(text)
    assert result == text

  def test_empty_text(self):
    """Empty text should return empty."""
    assert redact_api_key("") == ""
    assert redact_api_key(None) is None

  def test_no_key_in_text(self):
    """Text without API keys should pass through."""
    text = "Normal message without keys"
    assert redact_api_key(text) == text

class TestTruncatePrompt:
  """Tests for prompt truncation."""

  def test_short_prompt_unchanged(self):
    """Short prompts should pass through unchanged."""
    prompt = "Hello world"
    assert truncate_prompt(prompt) == prompt

  def test_long_prompt_truncated(self):
    """Long prompts should be truncated with ellipsis."""
    prompt = "x" * 500
    result = truncate_prompt(prompt, max_length=200)
    assert len(result) == 203
    assert result.endswith("...")

  def test_custom_max_length(self):
    """Custom max_length should be respected."""
    prompt = "y" * 100
    result = truncate_prompt(prompt, max_length=50)
    assert len(result) == 53

  def test_empty_prompt(self):
    """Empty prompt should return empty."""
    assert truncate_prompt("") == ""
    assert truncate_prompt(None) is None

  def test_exact_length_not_truncated(self):
    """Prompt at exact max_length should NOT be truncated."""
    prompt = "z" * 200
    result = truncate_prompt(prompt, max_length=200)
    assert result == prompt
    assert not result.endswith("...")

class TestAnonymizePath:
  """Tests for path anonymization (GDPR compliance)."""

  def test_macos_home_path(self):
    """macOS home paths should anonymize username."""
    path = "/Users/john/project/file.py"
    result = anonymize_path(path)
    assert result == "/Users/[USER]/project/file.py"
    assert "john" not in result

  def test_linux_home_path(self):
    """Linux home paths should anonymize username."""
    path = "/home/jane/app/config.toml"
    result = anonymize_path(path)
    assert result == "/home/[USER]/app/config.toml"
    assert "jane" not in result

  def test_windows_path(self):
    """Windows paths should anonymize username."""
    path = r"C:\Users\alice\Documents\file.txt"
    result = anonymize_path(path)
    assert "[USER]" in result
    assert "alice" not in result

  def test_system_path_unchanged(self):
    """System paths without usernames should pass through."""
    path = "/var/log/app.log"
    assert anonymize_path(path) == path

  def test_empty_path(self):
    """Empty path should return empty."""
    assert anonymize_path("") == ""
    assert anonymize_path(None) is None

class TestSanitizeLogEntry:
  """Tests for full log entry sanitization."""

  def test_sanitize_ip_address(self):
    """IP address should be obfuscated."""
    entry = {"ip_address": "192.168.1.100"}
    result = sanitize_log_entry(entry)
    assert result["ip_address"] == "192.168.1.xxx"

  def test_sanitize_api_key_in_message(self):
    """API keys in message should be redacted."""
    key = "a" * 64
    entry = {"message": f"Request with key {key}"}
    result = sanitize_log_entry(entry)
    assert "[REDACTED_API_KEY]" in result["message"]
    assert key not in result["message"]

  def test_sanitize_api_key_in_details(self):
    """API keys in details should be redacted."""
    key = "b" * 64
    entry = {"details": {"auth_header": key}}
    result = sanitize_log_entry(entry)
    assert "[REDACTED_API_KEY]" in result["details"]["auth_header"]

  def test_sanitize_path_in_details(self):
    """Paths in details should be anonymized."""
    entry = {"details": {"path": "/Users/admin/secret/file.txt"}}
    result = sanitize_log_entry(entry)
    assert "[USER]" in result["details"]["path"]
    assert "admin" not in result["details"]["path"]

  def test_truncate_prompt_in_details(self):
    """Long prompts in details should be truncated."""
    entry = {"details": {"prompt": "x" * 500}}
    result = sanitize_log_entry(entry)
    assert len(result["details"]["prompt"]) <= 203

  def test_redact_query_params_in_endpoint(self):
    """Query parameters in endpoint should be redacted."""
    entry = {"endpoint": "/api/chat?token=secret123&user=admin"}
    result = sanitize_log_entry(entry)
    assert result["endpoint"] == "/api/chat?[REDACTED_PARAMS]"

  def test_combined_sanitization(self):
    """All sanitizations should work together."""
    entry = {
      "ip_address": "10.0.0.50",
      "message": f"Auth with key {'c' * 64}",
      "endpoint": "/api/data?key=xyz",
      "details": {
        "path": "/home/user/data.json",
        "prompt": "d" * 300,
      },
    }
    result = sanitize_log_entry(entry)

    assert result["ip_address"] == "10.0.0.xxx"
    assert "[REDACTED_API_KEY]" in result["message"]
    assert "[REDACTED_PARAMS]" in result["endpoint"]
    assert "[USER]" in result["details"]["path"]
    assert len(result["details"]["prompt"]) <= 203