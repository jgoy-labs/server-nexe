"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: plugins/security/sanitizer/workflow/nodes/sanitizer_node.py
Description: Nexe Server Component

www.jgoy.net
────────────────────────────────────
"""

from typing import Dict, Any, Optional
from dataclasses import dataclass

from nexe_flow.core.node import (
  Node,
  NodeMetadata,
  NodeInput,
  NodeOutput,
)
from plugins.security.sanitizer.module import get_sanitizer
from personality.i18n.resolve import t_modular

@dataclass
class SanitizerNodeConfig:
  """Configuration for the SANITIZER node."""
  fail_on_critical: bool = False
  enable_telemetry: bool = True

class SanitizerNode(Node):
  """
  Workflow node for SANITIZER (technical security).

  Detects jailbreaks and prompt injections.
  Does NOT block (graceful degradation), only flags and warns.

  Expected inputs:
  - text: str - Text to sanitize
  - user_message: str - Alias for text (compatibility)

  Outputs:
  - is_safe: bool - True if there are no critical threats
  - needs_intervention: bool - True if Auditor should activate Intervention
  - severity: str - "none" | "low" | "medium" | "high" | "critical"
  - threats: List[str] - Detected threats
  - clean_text: str - Processed text (same as input)
  - scan_time_ms: float - Scan time

  Graceful Degradation philosophy:
  - severity != critical -> continue (is_safe=True)
  - severity == critical -> optionally block (configurable)
  - needs_intervention -> Auditor activates Intervention
  """

  def __init__(self, config: Optional[SanitizerNodeConfig] = None):
    self.config = config or SanitizerNodeConfig()
    self._sanitizer = get_sanitizer()
    super().__init__()

  def get_metadata(self) -> NodeMetadata:
    """Return SANITIZER node metadata."""
    return NodeMetadata(
      id="sanitizer.check",
      name="SANITIZER Check",
      version="1.0.0",
      description=t_modular(
        "sanitizer.check.description",
        "Detect jailbreaks and prompt injections (technical security)"
      ),
      category="nexe_native",
      inputs=[
        NodeInput(
          name="text",
          type="string",
          required=False,
          description=t_modular(
            "sanitizer.check.input_text_desc",
            "Text to sanitize"
          )
        ),
        NodeInput(
          name="user_message",
          type="string",
          required=False,
          description=t_modular(
            "sanitizer.check.input_user_message_desc",
            "Alias for text"
          )
        ),
      ],
      outputs=[
        NodeOutput(
          name="is_safe",
          type="boolean",
          description=t_modular(
            "sanitizer.check.output_is_safe_desc",
            "True if there are no critical threats"
          )
        ),
        NodeOutput(
          name="needs_intervention",
          type="boolean",
          description=t_modular(
            "sanitizer.check.output_needs_intervention_desc",
            "True if the Auditor should activate Intervention"
          )
        ),
        NodeOutput(
          name="severity",
          type="string",
          description=t_modular(
            "sanitizer.check.output_severity_desc",
            "none|low|medium|high|critical"
          )
        ),
        NodeOutput(
          name="threats",
          type="array",
          description=t_modular(
            "sanitizer.check.output_threats_desc",
            "Detected threats"
          )
        ),
        NodeOutput(
          name="clean_text",
          type="string",
          description=t_modular(
            "sanitizer.check.output_clean_text_desc",
            "Processed text"
          )
        ),
        NodeOutput(
          name="scan_time_ms",
          type="number",
          description=t_modular(
            "sanitizer.check.output_scan_time_desc",
            "Scan time in ms"
          )
        ),
      ],
      icon="🛡️",
      color="#e74c3c"
    )

  async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute the SANITIZER node.

    Target time: <2ms
    """
    text = inputs.get("text") or inputs.get("user_message", "")

    result = self._sanitizer.sanitize(text)

    return {
      "is_safe": result.is_safe,
      "needs_intervention": result.needs_intervention,
      "severity": result.severity,
      "threats": result.threats_detected,
      "patterns_matched": result.patterns_matched,
      "clean_text": result.clean_text,
      "scan_time_ms": result.scan_time_ms,
      "text": text,
      "user_message": text,
    }
