"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: plugins/security/sanitizer/__init__.py
Description: SANITIZER - TECHNICAL security module (04.1)

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from .module import SanitizerModule, SanitizeResult, get_sanitizer
from .health import get_health

__all__ = [
  "SanitizerModule",
  "SanitizeResult",
  "get_sanitizer",
  "get_health",
]

MODULE_METADATA = {
  "name": "sanitizer",
  "version": "1.0.0",
  "description": "Technical security filter for jailbreaks and prompt injections",
  "author": "J.Goy",
  "pilar": "plugins",
  "order": "04.1",
  "dependencies": [],
  "blocks": ["audit"],
}