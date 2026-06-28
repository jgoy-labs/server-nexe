"""Tests for core/messages.py — coverage gaps."""
from unittest.mock import MagicMock


class TestGetMessage:
    def test_without_i18n_returns_fallback(self):
        from core.messages import get_message
        result = get_message(None, "core.bootstrap.invalid_ip")
        assert result == "Invalid IP address"

    def test_unknown_key_returns_key(self):
        from core.messages import get_message
        result = get_message(None, "nonexistent.key")
        assert result == "nonexistent.key"

    def test_with_format_kwargs(self):
        from core.messages import get_message
        result = get_message(None, "core.ollama.http_error", status=500)
        assert "500" in result

    def test_with_i18n_found(self):
        from core.messages import get_message
        mock_i18n = MagicMock()
        mock_i18n.t.return_value = "Translated message"
        result = get_message(mock_i18n, "some.key")
        assert result == "Translated message"

    def test_with_i18n_returns_key_fallback(self):
        from core.messages import get_message
        mock_i18n = MagicMock()
        mock_i18n.t.return_value = "some.key"
        result = get_message(mock_i18n, "some.key")
        assert result == "some.key"

    def test_with_i18n_exception(self):
        from core.messages import get_message
        mock_i18n = MagicMock()
        mock_i18n.t.side_effect = Exception("i18n error")
        result = get_message(mock_i18n, "core.bootstrap.invalid_ip")
        assert result == "Invalid IP address"

    def test_format_key_error_returns_template(self):
        """T15: the except (KeyError, IndexError) fallback in get_message must
        return the raw template when format() raises KeyError.

        The original test-theatre asserted:
            'status' in result or 'http_error' in result.lower() or '{' in result
        which is true for ANY return value (formatted string, raw key, raw template),
        so a broken except block that raised instead of returning template was invisible.

        Correct behaviour: calling get_message with a known template key but WITHOUT
        the required format kwarg must return the raw template unchanged (not raise,
        not return the key).

        Mutation target: change `except (KeyError, IndexError): return template` to
        `raise` in messages.py → this test raises instead of returning → RED.
        """
        from core.messages import get_message

        # "core.ollama.http_error" template = "Ollama error (HTTP {status})"
        # Calling without the required {status} kwarg triggers KeyError inside format().
        result = get_message(None, "core.ollama.http_error")  # no status= kwarg

        assert result == "Ollama error (HTTP {status})", (
            f"Expected raw template on KeyError fallback, got: {result!r}"
        )

