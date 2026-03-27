"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: plugins/security_logger/sanitizers.py
Description: Sanitization functions for security logs (GDPR compliance).

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import re
from typing import Dict, Any

def obfuscate_ip(ip: str) -> str:
  """
  Obfuscate IP address for GDPR compliance.

  Keeps first 3 octets, masks last octet.
  Example: 192.168.1.42 → 192.168.1.xxx

  Localhost addresses (127.x.x.x, ::1) are NOT obfuscated as they're not personal data.

  Args:
    ip: IP address to obfuscate

  Returns:
    Obfuscated IP address
  """
  if not ip or ip == "unknown":
    return ip

  if ip.startswith("127.") or ip == "::1" or ip == "localhost":
    return ip

  parts = ip.split('.')
  if len(parts) == 4:
    return f"{parts[0]}.{parts[1]}.{parts[2]}.xxx"
  return ip

def redact_api_key(text: str) -> str:
  """
  Redact API keys from text (hex strings 32-128 chars).

  Args:
    text: Text that may contain API keys

  Returns:
    Text with API keys redacted
  """
  if not text:
    return text
  return re.sub(r'\b[a-f0-9]{32,128}\b', '[REDACTED_API_KEY]', text, flags=re.IGNORECASE)

def truncate_prompt(prompt: str, max_length: int = 200) -> str:
  """
  Truncate long prompts for log storage.

  Args:
    prompt: Prompt to truncate
    max_length: Maximum length

  Returns:
    Truncated prompt with ellipsis
  """
  if not prompt:
    return prompt
  if len(prompt) <= max_length:
    return prompt
  return prompt[:max_length] + "..."

def anonymize_path(path: str) -> str:
  """
  Anonymize filesystem paths (GDPR - remove usernames).

  Examples:
    /Users/john/project → /Users/[USER]/project
    /home/jane/app → /home/[USER]/app

  Args:
    path: File path to anonymize

  Returns:
    Anonymized path
  """
  if not path:
    return path

  path = re.sub(r'/Users/[^/]+', '/Users/[USER]', path)
  path = re.sub(r'/home/[^/]+', '/home/[USER]', path)

  path = re.sub(r'C:\\Users\\[^\\]+', r'C:\\Users\\[USER]', path)

  return path

def sanitize_log_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
  """
  Sanitize a log entry before writing.

  Apply all sanitization rules

  Args:
    entry: Log entry dict

  Returns:
    Sanitized log entry
  """
  sanitized = entry.copy()

  if 'ip_address' in sanitized and sanitized['ip_address']:
    sanitized['ip_address'] = obfuscate_ip(sanitized['ip_address'])

  if 'message' in sanitized:
    sanitized['message'] = redact_api_key(sanitized['message'])

  if 'details' in sanitized and isinstance(sanitized['details'], dict):
    for key, value in sanitized['details'].items():
      if isinstance(value, str):
        sanitized['details'][key] = redact_api_key(value)

      if key in ('prompt', 'input_data', 'attempted_path'):
        sanitized['details'][key] = truncate_prompt(str(value), 200)

      if key in ('path', 'attempted_path', 'file_path'):
        sanitized['details'][key] = anonymize_path(str(value))

  if 'endpoint' in sanitized and sanitized['endpoint']:
    endpoint = sanitized['endpoint']
    if '?' in endpoint:
      sanitized['endpoint'] = endpoint.split('?')[0] + '?[REDACTED_PARAMS]'

  return sanitized

__all__ = [
  "obfuscate_ip",
  "redact_api_key",
  "truncate_prompt",
  "anonymize_path",
  "sanitize_log_entry",
]