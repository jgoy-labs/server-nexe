"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: plugins/security/sanitizer/__init__.py
Description: SANITIZER - Mòdul de seguretat TÈCNICA (04.1)

www.jgoy.net
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
  "description": "Filtre de seguretat TÈCNICA per jailbreaks i prompt injections",
  "author": "J.Goy",
  "pilar": "plugins",
  "order": "04.1",
  "dependencies": [],
  "blocks": ["audit"],
}