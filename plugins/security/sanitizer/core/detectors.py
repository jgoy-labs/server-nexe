"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: plugins/security/sanitizer/core/detectors.py
Description: Detection functions for jailbreaks and prompt injections.

www.jgoy.net
────────────────────────────────────
"""

from typing import Optional, Tuple, List
from .patterns import (
  COMBINED_JAILBREAK,
  COMBINED_INJECTION,
  MAX_SCAN_LENGTH,
  SEVERITY_KEYWORDS,
)

def detect_jailbreak(text: str) -> Tuple[bool, Optional[str]]:
  """
  Detect jailbreak patterns in text.

  Args:
    text: Text to analyze

  Returns:
    Tuple[bool, Optional[str]]: (detected, matched_pattern)

  Target time: <0.5ms
  """
  if not text:
    return False, None

  scan_text = text[:MAX_SCAN_LENGTH]

  match = COMBINED_JAILBREAK.search(scan_text)
  if match:
    return True, match.group()

  return False, None

def detect_prompt_injection(text: str) -> Tuple[bool, Optional[str]]:
  """
  Detect prompt injection patterns in text.

  Args:
    text: Text to analyze

  Returns:
    Tuple[bool, Optional[str]]: (detected, matched_pattern)

  Target time: <0.5ms
  """
  if not text:
    return False, None

  scan_text = text[:MAX_SCAN_LENGTH]

  match = COMBINED_INJECTION.search(scan_text)
  if match:
    return True, match.group()

  return False, None

def get_severity(threats: List[str]) -> str:
  """
  Compute severity based on detected threats.

  Args:
    threats: List of detected patterns/threats (matched text)

  Returns:
    str: "none" | "low" | "medium" | "high" | "critical"
  """
  if not threats:
    return "none"

  severity_order = ["none", "low", "medium", "high", "critical"]
  max_severity = "low"

  all_threats_text = " ".join(t.lower() for t in threats if t)

  for severity in ["critical", "high", "medium"]:
    keywords = SEVERITY_KEYWORDS.get(severity, [])
    for keyword in keywords:
      if keyword.lower() in all_threats_text:
        if severity_order.index(severity) > severity_order.index(max_severity):
          max_severity = severity

  return max_severity

def detect_all(text: str) -> Tuple[List[str], str]:
  """
  Detect all threats and compute severity.

  Args:
    text: Text to analyze

  Returns:
    Tuple[List[str], str]: (threats_list, severity)
  """
  threats = []

  jailbreak_detected, jailbreak_pattern = detect_jailbreak(text)
  if jailbreak_detected and jailbreak_pattern:
    threats.append(f"jailbreak:{jailbreak_pattern}")

  injection_detected, injection_pattern = detect_prompt_injection(text)
  if injection_detected and injection_pattern:
    threats.append(f"injection:{injection_pattern}")

  severity = get_severity(threats)

  return threats, severity
