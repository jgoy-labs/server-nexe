"""
Tests for plugins/security/sanitizer/health.py - targeting uncovered lines.
Lines: 42-44 (patterns_loaded error), 56-58 (regex_compiled error),
       73-78 (sanitizer high latency/error), 90-93 (jailbreak not detected),
       105-108 (injection not detected).
"""

import pytest
from unittest.mock import patch, MagicMock
import time


class TestGetHealthPatternsError:
    """Test lines 42-44: exception loading patterns."""

    def test_patterns_load_exception(self):
        with patch("plugins.security.sanitizer.health.JAILBREAK_PATTERNS",
                    new_callable=lambda: property(lambda s: (_ for _ in ()).throw(Exception("bad patterns")))):
            # Simpler: patch len() to fail
            pass

        # Alternative approach: mock the patterns to raise on len()
        from plugins.security.sanitizer.health import get_health

        mock_patterns = MagicMock()
        mock_patterns.__len__ = MagicMock(side_effect=Exception("Patterns corrupted"))

        with patch("plugins.security.sanitizer.health.JAILBREAK_PATTERNS", mock_patterns):
            result = get_health()
            assert result["checks"]["patterns_loaded"]["status"] == "error"
            assert result["healthy"] is False


class TestGetHealthRegexError:
    """Test lines 56-58: exception checking compiled regex."""

    def test_regex_compiled_exception(self):
        from plugins.security.sanitizer.health import get_health

        # The try block at lines 46-55 evaluates COMBINED_JAILBREAK is not None
        # We need to make the entire block raise. Use a property descriptor proxy.
        class RaisingOnAccess:
            """Descriptor that raises when the attribute is accessed."""
            def __get__(self, obj, objtype=None):
                raise RuntimeError("Cannot access compiled regex")

        # Simplest: patch the entire block to raise by patching COMBINED_JAILBREAK
        # so that `is not None` raises
        class BadNone:
            def __ne__(self, other):
                raise RuntimeError("Bad comparison")

        # Actually, `X is not None` doesn't call __ne__, it's identity check.
        # So we can't raise from that. Instead, test the error path by making
        # COMBINED_INJECTION raise an exception when checked with `is not None`.
        # Since `is not None` never raises, we'll test with COMBINED_JAILBREAK = None.
        with patch("plugins.security.sanitizer.health.COMBINED_JAILBREAK", None):
            result = get_health()
            assert result["checks"]["regex_compiled"]["status"] == "error"
            assert result["checks"]["regex_compiled"]["jailbreak_compiled"] is False


class TestGetHealthSanitizerFunctional:
    """Test lines 73-78: sanitizer functional with high latency or error."""

    def test_sanitizer_functional_error(self):
        from plugins.security.sanitizer.health import get_health

        mock_sanitizer = MagicMock()
        mock_sanitizer.sanitize.side_effect = Exception("Sanitizer broken")

        with patch("plugins.security.sanitizer.health.get_sanitizer", return_value=mock_sanitizer):
            result = get_health()
            assert result["checks"]["sanitizer_functional"]["status"] == "error"
            assert result["healthy"] is False

    def test_sanitizer_high_latency_warning(self):
        """Lines 72-74: latency > 2ms triggers warning."""
        from plugins.security.sanitizer.health import get_health

        mock_result = MagicMock()
        mock_result.is_safe = True

        mock_sanitizer = MagicMock()

        def slow_sanitize(text):
            time.sleep(0.005)  # 5ms > 2ms threshold
            return mock_result

        mock_sanitizer.sanitize = slow_sanitize
        mock_sanitizer.get_patterns_version.return_value = "1.0"

        with patch("plugins.security.sanitizer.health.get_sanitizer", return_value=mock_sanitizer):
            result = get_health()
            check = result["checks"]["sanitizer_functional"]
            assert check["status"] == "warning"
            assert "latency" in check.get("warning", "")


class TestGetHealthJailbreakDetection:
    """Test lines 90-93: jailbreak not detected."""

    def test_jailbreak_not_detected_sets_error(self):
        """Lines 89-90: when jailbreak is NOT detected, status is error."""
        from plugins.security.sanitizer.health import get_health

        # Normal sanitizer for functional check
        mock_result_safe = MagicMock()
        mock_result_safe.is_safe = True

        # Jailbreak not detected
        mock_result_no_jb = MagicMock()
        mock_result_no_jb.threats_detected = []  # no jailbreak detected

        mock_sanitizer = MagicMock()
        mock_sanitizer.sanitize = MagicMock(side_effect=[
            mock_result_safe,      # functional check
            mock_result_no_jb,     # jailbreak check - NOT detected
            MagicMock(threats_detected=["prompt_injection"]),  # injection check
        ])
        mock_sanitizer.get_patterns_version.return_value = "1.0"

        with patch("plugins.security.sanitizer.health.get_sanitizer", return_value=mock_sanitizer):
            result = get_health()
            assert result["checks"]["jailbreak_detection"]["status"] == "error"
            assert result["checks"]["jailbreak_detection"]["test_passed"] is False
            assert result["healthy"] is False

    def test_jailbreak_detection_exception(self):
        """Lines 91-93: exception during jailbreak detection."""
        from plugins.security.sanitizer.health import get_health

        mock_result_safe = MagicMock()
        mock_result_safe.is_safe = True

        call_count = [0]
        def side_effect_fn(text):
            call_count[0] += 1
            if call_count[0] == 1:
                return mock_result_safe
            elif call_count[0] == 2:
                raise Exception("Jailbreak check error")
            else:
                return MagicMock(threats_detected=["prompt_injection"])

        mock_sanitizer = MagicMock()
        mock_sanitizer.sanitize = side_effect_fn
        mock_sanitizer.get_patterns_version.return_value = "1.0"

        with patch("plugins.security.sanitizer.health.get_sanitizer", return_value=mock_sanitizer):
            result = get_health()
            assert result["checks"]["jailbreak_detection"]["status"] == "error"
            assert result["healthy"] is False


class TestGetHealthInjectionDetection:
    """Test lines 105-108: injection not detected."""

    def test_injection_not_detected_sets_error(self):
        """Lines 104-105: when injection is NOT detected, status is error."""
        from plugins.security.sanitizer.health import get_health

        mock_result_safe = MagicMock()
        mock_result_safe.is_safe = True

        mock_result_jb = MagicMock()
        mock_result_jb.threats_detected = ["jailbreak"]

        mock_result_no_inj = MagicMock()
        mock_result_no_inj.threats_detected = []  # no injection detected

        mock_sanitizer = MagicMock()
        mock_sanitizer.sanitize = MagicMock(side_effect=[
            mock_result_safe,       # functional check
            mock_result_jb,         # jailbreak check - detected OK
            mock_result_no_inj,     # injection check - NOT detected
        ])
        mock_sanitizer.get_patterns_version.return_value = "1.0"

        with patch("plugins.security.sanitizer.health.get_sanitizer", return_value=mock_sanitizer):
            result = get_health()
            assert result["checks"]["injection_detection"]["status"] == "error"
            assert result["checks"]["injection_detection"]["test_passed"] is False
            assert result["healthy"] is False

    def test_injection_detection_exception(self):
        """Lines 106-108: exception during injection detection."""
        from plugins.security.sanitizer.health import get_health

        mock_result_safe = MagicMock()
        mock_result_safe.is_safe = True

        mock_result_jb = MagicMock()
        mock_result_jb.threats_detected = ["jailbreak"]

        call_count = [0]
        def side_effect_fn(text):
            call_count[0] += 1
            if call_count[0] == 1:
                return mock_result_safe
            elif call_count[0] == 2:
                return mock_result_jb
            else:
                raise Exception("Injection check error")

        mock_sanitizer = MagicMock()
        mock_sanitizer.sanitize = side_effect_fn
        mock_sanitizer.get_patterns_version.return_value = "1.0"

        with patch("plugins.security.sanitizer.health.get_sanitizer", return_value=mock_sanitizer):
            result = get_health()
            assert result["checks"]["injection_detection"]["status"] == "error"
            assert result["healthy"] is False
