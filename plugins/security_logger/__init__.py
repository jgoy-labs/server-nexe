"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy
Location: plugins/security_logger/__init__.py
Description: Stub de retrocompatibilitat. El modul real viu a plugins/security/security_logger/.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

# Retrocompatibilitat: re-exporta tot des de la nova ubicacio
from plugins.security.security_logger import (
  SecurityEventType,
  SecuritySeverity,
  obfuscate_ip,
  redact_api_key,
  truncate_prompt,
  anonymize_path,
  sanitize_log_entry,
  SecurityEventLogger,
  SecurityLoggerHelpers,
  get_security_logger,
)

__all__ = [
  "SecurityEventType",
  "SecuritySeverity",
  "obfuscate_ip",
  "redact_api_key",
  "truncate_prompt",
  "anonymize_path",
  "sanitize_log_entry",
  "SecurityEventLogger",
  "SecurityLoggerHelpers",
  "get_security_logger",
]

__version__ = "2.0.0"
__author__ = "Jordi Goy"
__description__ = "Stub retrocompat — real module at plugins/security/security_logger/"
