"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/memory_facts/__init__.py
Description: Memory facts in the core — the helper, its port, its intents.

Named "memory facts" (what the column manipulates) because `core/memory/`
would collide with the top-level `memory/` package.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from core.memory_facts.attach import attach_memory_helper, helper_for
from core.memory_facts.helper import MemoryHelper
from core.memory_facts.intent_patterns import (
    detect_delete_intent,
    detect_intent,
    detect_save_intent,
    matches_clear_all_confirm,
)
from core.memory_facts.port import MemoryPort

__all__ = [
    "MemoryHelper",
    "MemoryPort",
    "attach_memory_helper",
    "helper_for",
    "detect_intent",
    "detect_save_intent",
    "detect_delete_intent",
    "matches_clear_all_confirm",
]
