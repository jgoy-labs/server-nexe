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
  Result of sanitizing an input.

  Attributes:
    clean_text: Text returned to the caller (today: the original; this module detects, it does not rewrite)
    is_safe: True if the input is safe to process
    threats_detected: List of detected threats
    severity: "none" | "low" | "medium" | "high" | "critical"
    needs_intervention: If True, Auditor must activate Intervention
    patterns_matched: Specific patterns that matched (for logging)
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
  reaches the philosophical modules (Auditor, BRÚIXOLA).

  NOTE: TECHNICAL security only. PHILOSOPHICAL security
  (identity manipulation) is handled by Intervention inside Auditor.

  Target times:
  - sanitize(): <2ms
  - is_safe(): <1ms
  """

  PATTERNS_VERSION = "1.0.0"

  def __init__(self):
    """Initializes the Sanitizer."""
    self._initialized = True
    self._init_time = datetime.now(timezone.utc)

  def sanitize(self, text: str) -> SanitizeResult:
    """
    Detects jailbreaks and prompt injections. Does not rewrite the text.

    Args:
      text: User input text

    Returns:
      SanitizeResult with the analysis result

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

    # B129: is_safe must agree with the .is_safe() method (False on ANY threat).
    # The previous `severity != "critical"` reported is_safe=True for medium/high
    # threats, contradicting the field docstring and the method. The HTTP block
    # gate uses `severity`, not this field, so this only fixes the field's own
    # semantics (and its log line).
    is_safe = len(threats) == 0

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
    Quick check if the input is safe.

    Args:
      text: Text to verify

    Returns:
      True if safe, False if not

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
  """Return the singleton Sanitizer instance."""
  global _sanitizer_instance
  if _sanitizer_instance is None:
    _sanitizer_instance = SanitizerModule()
  return _sanitizer_instance


def apply_user_text_sanitizer(text: str) -> str:
  """Shared gate for /chat/completions AND /ui/chat (D-I / D-G).

  The module is a detector, not a rewriter (D-B): high/critical → HTTP 400.
  If it cannot load or sanitize() raises, the text is returned unchanged
  and that fact is logged at WARNING — never as a rewrite, never at debug.
  """
  from fastapi import HTTPException
  import logging
  _log = logging.getLogger(__name__)
  try:
    sanitizer = get_sanitizer()
  except Exception as exc:
    # D-G / #872: this used to be debug (invisible in normal operation).
    _log.warning("SanitizerModule unavailable, skipping: %s", exc)
    return text
  try:
    result = sanitizer.sanitize(text)
  except Exception as exc:
    _log.warning("SanitizerModule.sanitize raised, keeping original text: %s", exc)
    return text
  if result.severity in ("high", "critical"):
    _log.warning(
      "SanitizerModule blocked %s-severity input (threats=%s, patterns=%s)",
      result.severity,
      result.threats_detected,
      result.patterns_matched,
    )
    raise HTTPException(
      status_code=400,
      detail={
        "error": "input_rejected_by_sanitizer",
        "severity": result.severity,
        "threats": result.threats_detected,
      },
    )
  if not result.is_safe:
    _log.info(
      "SanitizerModule flagged user input (severity=%s, threats=%s)",
      result.severity,
      result.threats_detected,
    )
  return result.clean_text