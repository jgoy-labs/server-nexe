"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: plugins/security/sanitizer/module.py
Description: SANITIZER - TECHNICAL security module to filter jailbreaks and

www.jgoy.net
────────────────────────────────────
"""

from dataclasses import dataclass, field
from typing import List, Optional
from datetime import datetime

from .core.patterns import MAX_SCAN_LENGTH, MAX_INPUT_LENGTH
from .core.detectors import detect_jailbreak, detect_prompt_injection, get_severity

@dataclass
class SanitizeResult:
  """
  Result of input sanitization.

  Attributes:
    clean_text: Cleaned text (or original if safe)
    is_safe: True if the input is safe to process
    threats_detected: List of detected threats
    severity: "none" | "low" | "medium" | "high" | "critical"
    needs_intervention: If True, Auditor must activate Intervention
    patterns_matched: Specific matched patterns (for logging)
    scan_time_ms: Scan time in ms
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
  SANITIZER - TECHNICAL security filter.

  Detects jailbreaks and prompt injections before the input
  reaches philosophical modules (Auditor, BRÚIXOLA).

  NOTE: Technical security only. PHILOSOPHICAL security
  (identity manipulation) is handled by Intervention inside Auditor.

  Target timings:
  - sanitize(): <2ms
  - is_safe(): <1ms
  """

  PATTERNS_VERSION = "1.0.0"

  def __init__(self):
    """Initialize the Sanitizer."""
    self._initialized = True
    self._init_time = datetime.now()

  def sanitize(self, text: str) -> SanitizeResult:
    """
    Sanitize the input and detect threats.

    Args:
      text: User input text

    Returns:
      SanitizeResult with analysis outcome

    Target time: <2ms
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
    Fast check whether the input is safe.

    Args:
      text: Text to check

    Returns:
      True if safe, False otherwise

    Target time: <1ms
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
  """Get the Sanitizer singleton instance."""
  global _sanitizer_instance
  if _sanitizer_instance is None:
    _sanitizer_instance = SanitizerModule()
  return _sanitizer_instance
