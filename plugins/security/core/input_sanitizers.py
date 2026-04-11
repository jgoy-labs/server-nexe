"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: plugins/security/core/input_sanitizers.py
Description: Input sanitisation. Validates strings and dicts against XSS, SQL injection, etc.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import html
import re
from typing import Optional, Dict, Any
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

_MEM_TAG_RE = re.compile(
  r'(^|\n)\s*\[(?:MEM_SAVE|MEMORIA|MEM|MEMORY|SYSTEM|ASSISTANT|TOOL|FUNCTION|USER)(?:\s*[:=][^\]]*?)?\]',
  re.IGNORECASE,
)

_JAILBREAK_PATTERNS = [
  # Catalan: "ignora [totes/les/la/els/el ...] instrucci(ó|ons?) anterior[s]?"
  # Singular: "instrucció" (ca, accent); plural: "instruccions" / "instruccion"
  # Also covers Spanish "instruccion(es)" by sharing the "on" branch.
  re.compile(
    r'ignora\s+(?:totes?\s+)?(?:les\s+|la\s+|els\s+|el\s+)?instrucci(?:ó|ons?)\s+anteriors?',
    re.IGNORECASE,
  ),
  re.compile(r'ignore\s+(all\s+)?(previous\s+|prior\s+)?instructions?', re.IGNORECASE),
  # Tight: requires article + word, prevents false positives like
  # "you are now at home", "you are now old enough", "you are now free".
  re.compile(r'you\s+are\s+now\s+(?:a|an)\s+\w+', re.IGNORECASE),
  # Catalan: "ets un/una <word(s)>? sense restriccions"
  # Flexible: accepts 0-40 chars between article and "sense restriccions"
  # to cover "ets un model sense restriccions", "ets una IA sense restriccions",
  # "ara ets una nova IA sense restriccions", etc.
  re.compile(
    r'ets\s+(?:un|una)[^\n]{0,40}?sense\s+restriccions',
    re.IGNORECASE,
  ),
  re.compile(r'forget\s+(all\s+)?(your\s+)?(rules|guidelines|instructions)', re.IGNORECASE),
  re.compile(r'pretend\s+(to\s+be|you\s+are|that\s+you)', re.IGNORECASE),
  re.compile(r'nou\s+sistema\s+prompt', re.IGNORECASE),
  re.compile(r'new\s+system\s+prompt', re.IGNORECASE),
  re.compile(r'\bDAN\s+mode\b', re.IGNORECASE),
  re.compile(r'\bjailbreak\b', re.IGNORECASE),
  re.compile(r'do\s+anything\s+now', re.IGNORECASE),
]


def detect_jailbreak_attempt(text: str) -> Optional[str]:
  """Detect common jailbreak patterns — speed-bump, NOT security.

  Returns the matched substring if a pattern fires, None otherwise.

  Warning: defense-in-depth only. Sophisticated attackers bypass this
  trivially via Unicode lookalikes, base64/gzip encoding, chained prompts,
  language switching, etc. For real protection use content moderation at
  the model level or a dedicated safety classifier.

  The point of this function is to catch naive copy-paste attempts from
  jailbreak forums, not determined adversaries.
  """
  if not text:
    return None
  for pat in _JAILBREAK_PATTERNS:
    m = pat.search(text)
    if m:
      return m.group(0)
  return None


def strip_memory_tags(text: str) -> str:
  """Strip memory/role-impersonation tags at line start from user input.

  P0.9.1 P1-2: regex is now anchored to line start (`^` or `\\n`) to avoid
  false positives on inline brackets like `[USER: Jordi]` or `[memoria]`
  used in normal writing.

  Covered tags (all case-insensitive):
    MEM_SAVE, MEMORIA, MEM, MEMORY, SYSTEM, ASSISTANT, TOOL, FUNCTION, USER

  Breaking changes from v0.9.0:
    - Mid-line tags are NO LONGER stripped (e.g. `"text [MEM_SAVE: x]"`)
    - `[SYSTEM]` without `:` or `=` now matches (was ignored before)
    - Multi-line: each anchored tag is stripped, preserving other content

  Newlines are preserved via capture group 1 (the matched `^` or `\\n`).
  """
  return _MEM_TAG_RE.sub(lambda m: m.group(1), text).strip()

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
  context: str = "param",
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
    context: Validation context — "param" (default), "path", or "chat".
             In "chat" context, command injection and LDAP detectors are
             skipped to avoid false positives when users discuss code.

  Returns:
    Validated (and possibly sanitized) string

  Raises:
    HTTPException: If validation fails
  """
  # In chat context, skip detectors prone to false positives with code snippets
  # Path traversal (`..`) triggers on normal ellipsis ("vei..." = HTTP 400)
  if context == "chat":
    check_command = False
    check_ldap = False
    check_path_traversal = False
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