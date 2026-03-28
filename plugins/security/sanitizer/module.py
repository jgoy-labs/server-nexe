"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: plugins/security/sanitizer/module.py
Description: SANITIZER - TECHNICAL security module for filtering jailbreaks and

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from dataclasses import dataclass, field
from typing import List, Optional
from datetime import datetime, timezone

from .core.patterns import MAX_SCAN_LENGTH, MAX_INPUT_LENGTH
from .core.detectors import detect_jailbreak, detect_prompt_injection, get_severity

@dataclass
class SanitizeResult:
  """
  Resultat de la sanitització d'un input.

  Attributes:
    clean_text: Text netejat (o original si és segur)
    is_safe: True si l'input és segur per processar
    threats_detected: Llista d'amenaces detectades
    severity: "none" | "low" | "medium" | "high" | "critical"
    needs_intervention: Si True, Auditor ha d'activar Intervenció
    patterns_matched: Patrons concrets que han fet match (per logging)
    scan_time_ms: Temps d'escaneig en ms
  """
  clean_text: str
  is_safe: bool
  threats_detected: List[str] = field(default_factory=list)
  severity: str = "none"
  needs_intervention: bool = False
  patterns_matched: List[str] = field(default_factory=list)
  scan_time_ms: float = 0.0

class SanitizerModule:
  """
  SANITIZER - Filtre de seguretat TÈCNICA.

  Detecta jailbreaks i prompt injections abans que l'input
  arribi als mòduls filosòfics (Auditor, BRÚIXOLA).

  NOTA: Només seguretat TÈCNICA. La seguretat FILOSÒFICA
  (manipulació d'identitat) la fa Intervenció dins Auditor.

  Temps objectiu:
  - sanitize(): <2ms
  - is_safe(): <1ms
  """

  PATTERNS_VERSION = "1.0.0"

  def __init__(self):
    """Inicialitza el Sanitizer."""
    self._initialized = True
    self._init_time = datetime.now(timezone.utc)

  def sanitize(self, text: str) -> SanitizeResult:
    """
    Sanititza l'input i detecta amenaces.

    Args:
      text: Text d'entrada de l'usuari

    Returns:
      SanitizeResult amb el resultat de l'anàlisi

    Temps objectiu: <2ms
    """
    import time
    start = time.perf_counter()

    if not text:
      return SanitizeResult(
        clean_text="",
        is_safe=True,
        severity="none",
      )

    if len(text) > MAX_INPUT_LENGTH:
      return SanitizeResult(
        clean_text=text[:MAX_INPUT_LENGTH],
        is_safe=False,
        threats_detected=["input_too_long"],
        severity="medium",
        needs_intervention=True,
        scan_time_ms=(time.perf_counter() - start) * 1000,
      )

    threats = []
    patterns = []

    jailbreak_detected, jailbreak_pattern = detect_jailbreak(text)
    if jailbreak_detected:
      threats.append("jailbreak")
      if jailbreak_pattern:
        patterns.append(jailbreak_pattern)

    injection_detected, injection_pattern = detect_prompt_injection(text)
    if injection_detected:
      threats.append("prompt_injection")
      if injection_pattern:
        patterns.append(injection_pattern)

    severity = get_severity(patterns)

    needs_intervention = severity in ["medium", "high", "critical"]

    is_safe = severity != "critical"

    scan_time = (time.perf_counter() - start) * 1000

    return SanitizeResult(
      clean_text=text,
      is_safe=is_safe,
      threats_detected=threats,
      severity=severity,
      needs_intervention=needs_intervention,
      patterns_matched=patterns,
      scan_time_ms=scan_time,
    )

  def is_safe(self, text: str) -> bool:
    """
    Check ràpid si l'input és segur.

    Args:
      text: Text a verificar

    Returns:
      True si és segur, False si no

    Temps objectiu: <1ms
    """
    if not text:
      return True

    if len(text) > MAX_INPUT_LENGTH:
      return False

    jailbreak_detected, _ = detect_jailbreak(text)
    if jailbreak_detected:
      return False

    injection_detected, _ = detect_prompt_injection(text)
    if injection_detected:
      return False

    return True

  def get_patterns_version(self) -> str:
    """Return the patterns version."""
    return self.PATTERNS_VERSION

  def get_stats(self) -> dict:
    """Return module statistics."""
    return {
      "patterns_version": self.PATTERNS_VERSION,
      "max_scan_length": MAX_SCAN_LENGTH,
      "max_input_length": MAX_INPUT_LENGTH,
      "initialized_at": self._init_time.isoformat(),
    }

_sanitizer_instance: Optional[SanitizerModule] = None

def get_sanitizer() -> SanitizerModule:
  """Return the singleton Sanitizer instance."""
  global _sanitizer_instance
  if _sanitizer_instance is None:
    _sanitizer_instance = SanitizerModule()
  return _sanitizer_instance