"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: plugins/security/sanitizer/core/patterns.py
Description: Precompiled patterns for jailbreak and prompt injection detection.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import re

MAX_SCAN_LENGTH = 5000

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

  # B031: system-prompt extraction via a technical pretext (debug/verification/maintenance/
  # diagnostics) asking for the SYSTEM instructions/configuration. The required proximity
  # to the system-object avoids false positives with "debug del meu codi" or "configuració del SO".
  r"(debug|verificaci[oó]n?|mantenim(ent|iento)?|diagn[oò]stic[oa]?)[^.?!\n]{0,40}(system\s*prompt|prompt\s+del?\s+sistema|instruccions?\s+del?\s+sistema|instruccion(es)?\s+del\s+sistema|configuraci[oó]n?\s+del?\s+sistema|system\s+(instructions|configuration))",
  # B031: reveal the OWN assistant's initial instructions/prompt (possessive required
  # → avoids FP with "necessito instruccions per..." or "mostra'm un exemple").
  r"(mostra|revela|recita|repeteix|imprimeix|ensenya|show|reveal|recite|repeat|print)[^.?!\n]{0,25}(your|teves|teu|tus|tu)\s+(initial\s+)?(system\s+)?(prompt\s+de\s+sistema|system\s*prompt|instruccions?|instruccion(es)?|instructions|setup)",
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
    # B031: the system-object of the extraction framing (only escalates within an already-matched threat)
    "configuració", "configuración", "configuration",
  ],
  "medium": ["[assistant]", "[user]", "```system", "[inst]"],
}