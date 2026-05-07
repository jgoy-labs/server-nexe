"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: plugins/security/sanitizer/workflow/nodes/resistencia_node.py
Description: Intervention Node - Predefined response when a jailbreak is detected.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import logging
from typing import Any, Dict, List

from nexe_flow.core.node import Node, NodeMetadata

logger = logging.getLogger(__name__)

RESISTANCE_RESPONSE = "Crec que hi ha un problema amb el teu missatge. Pots reformular?"

class InterventionNode(Node):
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
      node_type="intervention.respond",
      version="1.0.0",
      description="Generate resistance response when threats are detected",
      inputs={
        "threats": {
          "type": "array",
          "description": "List of detected threats",
          "required": False,
          "default": [],
        },
        "severity": {
          "type": "string",
          "description": "Severity level",
          "required": False,
          "default": "medium",
        },
      },
      outputs={
        "response": {"type": "string", "description": "Resistance response"},
        "activated": {"type": "boolean", "description": "Whether activated"},
        "threat_type": {"type": "string", "description": "Primary threat type"},
      },
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