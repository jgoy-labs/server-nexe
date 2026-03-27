"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: plugins/security/sanitizer/core/__init__.py
Description: SANITIZER core - Jailbreak and prompt injection detection for LLMs.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from .patterns import (
  JAILBREAK_PATTERNS,
  INJECTION_PATTERNS,
  COMBINED_JAILBREAK,
  COMBINED_INJECTION,
  MAX_SCAN_LENGTH,
)
from .detectors import (
  detect_jailbreak,
  detect_prompt_injection,
  get_severity,
)

__all__ = [
  "JAILBREAK_PATTERNS",
  "INJECTION_PATTERNS",
  "COMBINED_JAILBREAK",
  "COMBINED_INJECTION",
  "MAX_SCAN_LENGTH",
  "detect_jailbreak",
  "detect_prompt_injection",
  "get_severity",
]