"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: plugins/security/sanitizer/workflow/nodes/sanitizer_node.py
Description: Nexe Server Component

www.jgoy.net · https://server-nexe.org
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

@dataclass
class SanitizerNodeConfig:
  """Configuration for the SANITIZER node."""
  fail_on_critical: bool = False
  enable_telemetry: bool = True

class SanitizerNode(Node):
  """
  Workflow node for SANITIZER (TECHNICAL security).

  Detects jailbreaks and prompt injections.
  Does NOT block (graceful degradation), only marks and warns.

  Expected inputs:
  - text: str - Text to sanitize
  - user_message: str - Alias for text (compatibility)

  Outputs:
  - is_safe: bool - True if no critical threats
  - needs_intervention: bool - True if Auditor must activate Intervention
  - severity: str - "none" | "low" | "medium" | "high" | "critical"
  - threats: List[str] - Detected threats
  - clean_text: str - Processed text (same as input)
  - scan_time_ms: float - Scan time

  Graceful Degradation philosophy:
  - severity != critical -> continue (is_safe=True)
  - severity == critical -> OPTIONALLY block (configurable)
  - needs_intervention -> Auditor activates Intervention
  """

  def __init__(self, config: Optional[SanitizerNodeConfig] = None):
    self.config = config or SanitizerNodeConfig()
    self._sanitizer = get_sanitizer()
    super().__init__()

  def get_metadata(self) -> NodeMetadata:
    """Returns the SANITIZER node metadata."""
    return NodeMetadata(
      id="sanitizer.check",
      name="SANITIZER Check",
      version="1.0.0",
      description="Detects jailbreaks and prompt injections (TECHNICAL security)",
      category="nexe_native",
      inputs=[
        NodeInput(name="text", type="string", required=False, description="Text to sanitize"),
        NodeInput(name="user_message", type="string", required=False, description="Alias for text"),
      ],
      outputs=[
        NodeOutput(name="is_safe", type="boolean", description="True if no critical threats"),
        NodeOutput(name="needs_intervention", type="boolean", description="True if Auditor should activate Intervention"),
        NodeOutput(name="severity", type="string", description="none|low|medium|high|critical"),
        NodeOutput(name="threats", type="array", description="Detected threats"),
        NodeOutput(name="clean_text", type="string", description="Processed text"),
        NodeOutput(name="scan_time_ms", type="number", description="Scan time in ms"),
      ],
      icon="🛡️",
      color="#e74c3c"
    )

  async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
    """
    Executes the SANITIZER node.

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