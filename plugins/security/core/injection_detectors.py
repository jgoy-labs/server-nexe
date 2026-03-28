"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: plugins/security/core/injection_detectors.py
Description: Injection attack detectors. Detects SQL, XSS, NoSQL, command and path traversal.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import re
import unicodedata
from typing import Any

def detect_xss_attempt(text: str) -> bool:
  """
  Detect potential XSS attack patterns in input.

  Args:
    text: Input text to check

  Returns:
    True if XSS pattern detected, False otherwise

  Patterns checked:
    - <script> tags
    - javascript: protocol
    - on* event handlers (onclick, onerror, etc.)
    - <iframe> tags
    - data: URIs with script content
  """
  if not text:
    return False
  text = unicodedata.normalize('NFKC', text)

  text_lower = text.lower()

  xss_patterns = [
    r'<script[^>]*>',
    r'javascript:',
    r'on\w+\s*=',
    r'<iframe[^>]*>',
    r'data:text/html',
    r'<object[^>]*>',
    r'<embed[^>]*>',
    r'<svg[^>]*onload',
  ]

  for pattern in xss_patterns:
    if re.search(pattern, text_lower):
      return True

  return False

def detect_sql_injection(text: str) -> bool:
  """
  Detect potential SQL injection patterns in input.

  Args:
    text: Input text to check

  Returns:
    True if SQL injection pattern detected, False otherwise

  Note: In air-gapped Nexe 0.8, SQL injection is low risk (no external DB),
     but this validator provides defense-in-depth.
  """
  if not text:
    return False
  text = unicodedata.normalize('NFKC', text)

  text_lower = text.lower()

  sql_patterns = [
    r'\b(union|select|insert|update|delete|drop|create|alter)\b.*\bfrom\b',
    r';\s*(drop|delete|update|insert)',
    r'--\s',
    r'/\*.*\*/',
    r"'\s*(or|and)\s*'?\d+'\s*=",
    r'\bexec\b',
    r'\bexecute\b',
  ]

  for pattern in sql_patterns:
    if re.search(pattern, text_lower):
      return True

  return False

def detect_nosql_injection(data: Any) -> bool:
  """
  Detect potential NoSQL injection patterns in input data.

  Args:
    data: Input data (dict, str, or other)

  Returns:
    True if NoSQL injection pattern detected, False otherwise

  Patterns checked:
    - MongoDB operators ($where, $regex, $ne, etc.)
    - JavaScript code in strings
  """
  if isinstance(data, str):
    data = unicodedata.normalize('NFKC', data)
  if isinstance(data, dict):
    for key in data.keys():
      if isinstance(key, str) and key.startswith('$'):
        return True

      if detect_nosql_injection(data[key]):
        return True

  elif isinstance(data, str):
    nosql_patterns = [
      r'\$where\b',
      r'\$regex\b',
      r'\$ne\s*:',
      r'\$gt\s*:',
      r'\$lt\s*:',
      r'\bdb\.\w+\.\w+\(',
    ]
    for pattern in nosql_patterns:
      if re.search(pattern, data, re.IGNORECASE):
        return True

  elif isinstance(data, list):
    for item in data:
      if detect_nosql_injection(item):
        return True

  return False

def detect_command_injection(text: str) -> bool:
  """
  Detect potential command injection patterns in input.

  Args:
    text: Input text to check

  Returns:
    True if command injection pattern detected, False otherwise

  Patterns checked:
    - Shell metacharacters (;, |, &, `, $, etc.)
    - Command chaining
    - Backticks
  """
  if not text:
    return False
  text = unicodedata.normalize('NFKC', text)

  dangerous_chars = [
    ';',
    '|',
    '&',
    '`',
    '$(',
    '\n',
    '\r',
    '>',
    '<',
  ]

  for char in dangerous_chars:
    if char in text:
      return True

  return False

def detect_path_traversal(text: str) -> bool:
  """
  Detect potential path traversal patterns in input.

  Args:
    text: Input text to check

  Returns:
    True if path traversal pattern detected, False otherwise

  Note: This complements the existing validate_safe_path() function.
  """
  if not text:
    return False
  text = unicodedata.normalize('NFKC', text)

  traversal_patterns = [
    r'\.\.',
    r'%2e%2e',
    r'\.\./',
    r'\.\.\\\\',
    r'%252e%252e',
    r'/etc/',
    r'c:',
    r'\\\\',
  ]

  text_lower = text.lower()

  for pattern in traversal_patterns:
    if re.search(pattern, text_lower):
      return True

  return False

def detect_ldap_injection(text: str) -> bool:
  """
  Detect potential LDAP injection patterns in input.

  Args:
    text: Input text to check

  Returns:
    True if LDAP injection pattern detected, False otherwise

  Note: Low risk in air-gapped Nexe 0.8 (no LDAP), but included for completeness.
  """
  if not text:
    return False
  text = unicodedata.normalize('NFKC', text)

  ldap_special_chars = ['*', '(', ')', '\\', '\x00']

  for char in ldap_special_chars:
    if char in text:
      return True

  return False