"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: plugins/security/sanitizer/workflow/nodes/intervention_node.py
Description: Intervention Node - Predefined response when a jailbreak is detected.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import logging
from typing import Any, Dict, List

# nexe_flow is the (not-yet-shipped) workflow engine. Import it optionally so
# importing this dormant workflow subpackage does not crash a real install that
# lacks nexe_flow. Tests inject a mock nexe_flow in conftest.py, so the import
# succeeds there unchanged.
try:
  from nexe_flow.core.node import (
    Node,
    NodeMetadata,
    NodeInput,
    NodeOutput,
  )
  NEXE_FLOW_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only on real (unmocked) installs
  NEXE_FLOW_AVAILABLE = False

logger = logging.getLogger(__name__)

RESISTANCE_RESPONSE = "Crec que hi ha un problema amb el teu missatge. Pots reformular?"

if not NEXE_FLOW_AVAILABLE:
  # nexe_flow is not installed → the InterventionNode workflow node cannot be
  # defined (it subclasses nexe_flow's Node). Expose a None sentinel so the
  # subpackage stays importable and importers can degrade gracefully.
  InterventionNode = None  # type: ignore[assignment,misc]
else:
  class InterventionNode(Node):  # type: ignore[no-redef]
    """
    Intervention Node for Nexe.

    When the Sanitizer detects threats, this node:
    1. Generates an appropriate resistance response
    2. Stops the pipeline (it is terminal)
    3. Does not call the LLM (saves resources and avoids risks)

    Inputs:
      threats: List[str] - List of threats detected by the Sanitizer
      severity: str - Severity level ("low", "medium", "high", "critical")

    Outputs:
      response: str - Resistance response
      activated: bool - True (always, if executed)
      threat_type: str - Primary threat type
    """

    def get_metadata(self) -> NodeMetadata:
      return NodeMetadata(
        id="intervention.respond",
        name="Intervention Respond",
        version="1.0.0",
        description="Generate resistance response when threats are detected",
        category="nexe_native",
        inputs=[
          NodeInput(name="threats", type="array", required=False, default=[], description="List of detected threats"),
          NodeInput(name="severity", type="string", required=False, default="medium", description="Severity level"),
        ],
        outputs=[
          NodeOutput(name="response", type="string", description="Resistance response"),
          NodeOutput(name="activated", type="boolean", description="Whether activated"),
          NodeOutput(name="threat_type", type="string", description="Primary threat type"),
        ],
        icon="🛡️",
        color="#e74c3c",
      )

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
      """
      Generate resistance response based on detected threats.

      Args:
        inputs: Dict with threats and severity

      Returns:
        Dict with response, activated, threat_type
      """
      threats: List[str] = inputs.get("threats", [])
      severity: str = inputs.get("severity", "medium")

      logger.warning(
        "RESISTANCE ACTIVATED - Threats: %s, Severity: %s",
        threats, severity
      )

      threat_type = threats[0] if threats else "unknown"

      response = RESISTANCE_RESPONSE

      return {
        "response": response,
        "activated": True,
        "threat_type": threat_type,
      }