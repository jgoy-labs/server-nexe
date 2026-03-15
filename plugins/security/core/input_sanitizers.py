"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: plugins/security/core/input_sanitizers.py
Description: Sanitització d'inputs. Valida strings i dicts contra XSS, SQL injection, etc.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import html
from typing import Optional, List, Dict, Any
from fastapi import HTTPException

from .injection_detectors import (
  detect_xss_attempt,
  detect_sql_injection,
  detect_nosql_injection,
  detect_command_injection,
  detect_path_traversal,
  detect_ldap_injection,
)

from .messages import get_message

def sanitize_html(text: str) -> str:
  """
  Sanitize HTML content to prevent XSS attacks.

  Escapes all HTML tags unconditionally — no whitelist supported.

  Args:
    text: Raw text that may contain HTML

  Returns:
    Text with all HTML characters escaped

  Examples:
    >>> sanitize_html("<script>alert('xss')</script>")
    "&lt;script&gt;alert('xss')&lt;/script&gt;"
  """
  if not text:
    return text

  return html.escape(text)

def validate_string_input(
  text: str,
  max_length: Optional[int] = None,
  min_length: Optional[int] = None,
  allow_html: bool = False,
  check_xss: bool = True,
  check_sql: bool = True,
  check_nosql: bool = False,
  check_command: bool = True,
  check_path_traversal: bool = True,
  check_ldap: bool = False,
  i18n=None,
) -> str:
  """
  Comprehensive string input validation with i18n support.

  Args:
    text: Input string to validate
    max_length: Maximum allowed length
    min_length: Minimum required length
    allow_html: Whether to allow HTML (if False, will be escaped)
    check_xss: Check for XSS patterns
    check_sql: Check for SQL injection
    check_nosql: Check for NoSQL injection
    check_command: Check for command injection
    check_path_traversal: Check for path traversal
    check_ldap: Check for LDAP injection
    i18n: I18n manager for translated error messages (optional)

  Returns:
    Validated (and possibly sanitized) string

  Raises:
    HTTPException: If validation fails
  """
  if not isinstance(text, str):
    raise HTTPException(
      400,
      get_message(i18n, 'security.sanitizers.input_not_string')
    )

  if max_length is not None and len(text) > max_length:
    raise HTTPException(
      400,
      get_message(i18n, 'security.sanitizers.input_too_long',
            max_length=max_length)
    )

  if min_length is not None and len(text) < min_length:
    raise HTTPException(
      400,
      get_message(i18n, 'security.sanitizers.input_too_short',
            min_length=min_length)
    )

  if check_xss and detect_xss_attempt(text):
    raise HTTPException(
      400,
      get_message(i18n, 'security.sanitizers.xss_detected')
    )

  if check_sql and detect_sql_injection(text):
    raise HTTPException(
      400,
      get_message(i18n, 'security.sanitizers.sql_injection_detected')
    )

  if check_command and detect_command_injection(text):
    raise HTTPException(
      400,
      get_message(i18n, 'security.sanitizers.command_injection_detected')
    )

  if check_path_traversal and detect_path_traversal(text):
    raise HTTPException(
      400,
      get_message(i18n, 'security.sanitizers.path_traversal_detected')
    )

  if check_ldap and detect_ldap_injection(text):
    raise HTTPException(
      400,
      get_message(i18n, 'security.sanitizers.ldap_injection_detected')
    )

  if not allow_html:
    text = sanitize_html(text)

  return text

def validate_dict_input(
  data: Dict[str, Any],
  check_nosql: bool = True,
  i18n=None
) -> Dict[str, Any]:
  """
  Validate dictionary input (e.g., JSON payloads) with i18n support.

  Args:
    data: Input dictionary to validate
    check_nosql: Check for NoSQL injection patterns
    i18n: I18n manager for translated error messages (optional)

  Returns:
    Validated dictionary

  Raises:
    HTTPException: If validation fails
  """
  if not isinstance(data, dict):
    raise HTTPException(
      400,
      get_message(i18n, 'security.sanitizers.input_not_dict')
    )

  if check_nosql and detect_nosql_injection(data):
    raise HTTPException(
      400,
      get_message(i18n, 'security.sanitizers.nosql_injection_detected')
    )

  return data