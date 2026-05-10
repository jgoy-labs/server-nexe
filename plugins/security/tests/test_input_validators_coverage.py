"""Tests for plugins/security/core/input_validators.py — facade re-exports."""


class TestInputValidatorsFacade:
    """Verify all expected symbols are re-exported."""

    def test_all_exports_present(self):
        from plugins.security.core.input_validators import __all__
        expected = [
            "detect_xss_attempt", "detect_sql_injection", "detect_nosql_injection",
            "detect_command_injection", "detect_path_traversal", "detect_ldap_injection",
            "sanitize_html", "validate_string_input", "validate_dict_input",
            "ALLOWED_CONTENT_TYPES", "ALLOWED_CHARSETS",
            "validate_content_type", "validate_charset",
            "validate_request_headers", "validate_request_params",
            "validate_request_path", "validate_all_request_inputs",
        ]
        for name in expected:
            assert name in __all__, f"{name} missing from __all__"

    def test_detection_functions_callable(self):
        from plugins.security.core.input_validators import (
            detect_xss_attempt, detect_sql_injection, detect_nosql_injection,
            detect_command_injection, detect_path_traversal, detect_ldap_injection,
        )
        for fn in [detect_xss_attempt, detect_sql_injection, detect_nosql_injection,
                    detect_command_injection, detect_path_traversal, detect_ldap_injection]:
            assert callable(fn)

    def test_sanitization_functions_callable(self):
        from plugins.security.core.input_validators import (
            sanitize_html, validate_string_input, validate_dict_input,
        )
        for fn in [sanitize_html, validate_string_input, validate_dict_input]:
            assert callable(fn)

    def test_request_validators_callable(self):
        from plugins.security.core.input_validators import (
            validate_content_type, validate_charset,
            validate_request_headers, validate_request_params,
            validate_request_path, validate_all_request_inputs,
        )
        for fn in [validate_content_type, validate_charset,
                    validate_request_headers, validate_request_params,
                    validate_request_path, validate_all_request_inputs]:
            assert callable(fn)

    def test_constants_are_sets(self):
        from plugins.security.core.input_validators import (
            ALLOWED_CONTENT_TYPES, ALLOWED_CHARSETS,
        )
        assert isinstance(ALLOWED_CONTENT_TYPES, set)
        assert isinstance(ALLOWED_CHARSETS, set)
        assert len(ALLOWED_CONTENT_TYPES) > 0
        assert len(ALLOWED_CHARSETS) > 0
