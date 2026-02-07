"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: plugins/security/sanitizer/core/patterns.py
Description: Precompiled patterns for detecting jailbreaks and prompt injections.

www.jgoy.net
────────────────────────────────────
"""

import re

MAX_SCAN_LENGTH = 2000

MAX_INPUT_LENGTH = 10000

JAILBREAK_PATTERNS = [
  r"ignore\s+(all\s+)?(previous\s+)?instructions?",
  r"disregard\s+(all\s+)?(previous\s+)?instructions?",
  r"forget\s+(your\s+)?rules?",
  r"forget\s+(all\s+)?(previous\s+)?instructions?",
  r"pretend\s+(that\s+)?you\s+are",
  r"you\s+are\s+now\s+",
  r"act\s+as\s+if",
  r"from\s+now\s+on\s+you\s+are",
  r"bypass\s+safety",
  r"bypass\s+(your\s+)?filters?",
  r"override\s+system",
  r"disable\s+filter",
  r"unlock\s+mode",
  r"developer\s+mode",
  r"jailbreak",
  r"DAN\s+mode",
  r"do\s+anything\s+now",
  r"new\s+system\s+prompt",
  r"ignore\s+your\s+training",
  r"ignore\s+your\s+guidelines",
  r"reveal\s+(your\s+)?system\s+prompt",
  r"show\s+(me\s+)?(your\s+)?system\s+prompt",

  r"ignora\s+(les\s+)?(anteriors\s+)?instruccions",
  r"ignora\s+(qualsevol\s+)?regla",
  r"oblida\s+(les\s+)?instruccions",
  r"oblida\s+(les\s+)?regles",
  r"revela\s+(el\s+)?system\s+prompt",
  r"mostra\s+(el\s+)?system\s+prompt",
  r"fes\s+veure\s+que\s+ets",
  r"ara\s+ets\s+",
  r"actua\s+com\s+si",
  r"comporta't\s+com",
  r"respon\s+com\s+si\s+fossis",
  r"passa\s+de\s+(les\s+)?instruccions",
  r"no\s+facis\s+cas\s+a\s+(les\s+)?instruccions",
  r"salta't\s+els\s+filtres",
  r"desactiva\s+(els\s+)?filtres",
  r"desactiva\s+la\s+seguretat",
  r"mode\s+desenvolupador",

  r"ignora\s+(las\s+)?instrucciones",
  r"olvida\s+(las\s+)?instrucciones",
  r"olvida\s+(las\s+)?reglas",
  r"revela\s+(el\s+)?system\s+prompt",
  r"muestra\s+(el\s+)?system\s+prompt",
  r"finge\s+que\s+eres",
  r"ahora\s+eres\s+",
  r"actúa\s+como\s+si",
]

INJECTION_PATTERNS = [
  r"\[system\]",
  r"\[/system\]",
  r"\[assistant\]",
  r"\[/assistant\]",
  r"\[user\]",
  r"\[/user\]",
  r"\[INST\]",
  r"\[/INST\]",
  r"<<SYS>>",
  r"<</SYS>>",
  r"<<SYSTEM>>",
  r"```system",
  r"```assistant",
  r"<\|system\|>",
  r"<\|assistant\|>",
  r"<\|user\|>",
  r"<\|im_start\|>",
  r"<\|im_end\|>",
]

COMBINED_JAILBREAK = re.compile(
  "|".join(f"(?:{p})" for p in JAILBREAK_PATTERNS),
  re.IGNORECASE
)

COMBINED_INJECTION = re.compile(
  "|".join(f"(?:{p})" for p in INJECTION_PATTERNS),
  re.IGNORECASE
)

SEVERITY_KEYWORDS = {
  "critical": [
    "dan mode", "jailbreak", "bypass safety", "override system", "do anything now",
  ],
  "high": [
    "ignore", "instructions", "forget", "rules", "pretend", "developer mode",
    "[system]", "<<sys>>", "<<system>>", "system prompt", "reveal",
    "ignora", "instruccions", "oblida", "regles", "revela", "mostra", "filtres", "seguretat", "comporta't", "respon",
    "instrucciones", "olvida", "reglas", "finge", "muestra",
  ],
  "medium": ["[assistant]", "[user]", "```system", "[inst]"],
}
