"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: plugins/security/sanitizer/workflow/nodes/resistencia_node.py
Description: Intervention node - predefined response when jailbreak is detected.

www.jgoy.net
────────────────────────────────────
"""

import logging
from typing import Any, Dict, List

from nexe_flow.core.node import Node, NodeMetadata
from personality.i18n.resolve import t_modular

logger = logging.getLogger(__name__)

RESISTANCE_RESPONSE = t_modular(
  "sanitizer.intervention.response",
  "I think there's a problem with your message. Can you rephrase?"
)

class InterventionNode(Node):
  """
  Intervention node for Nexe.

  When the Sanitizer detects threats, this node:
  1. Generates an appropriate resistance response
  2. Stops the pipeline (terminal)
  3. Does not call the LLM (saves resources and avoids risk)

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
      description=t_modular(
        "sanitizer.intervention.metadata_description",
        "Generate a resistance response when threats are detected"
      ),
      inputs={
        "threats": {
          "type": "array",
          "description": t_modular(
            "sanitizer.intervention.input_threats_desc",
            "List of detected threats"
          ),
          "required": False,
          "default": [],
        },
        "severity": {
          "type": "string",
          "description": t_modular(
            "sanitizer.intervention.input_severity_desc",
            "Severity level"
          ),
          "required": False,
          "default": "medium",
        },
      },
      outputs={
        "response": {"type": "string", "description": t_modular(
          "sanitizer.intervention.output_response_desc",
          "Resistance response"
        )},
        "activated": {"type": "boolean", "description": t_modular(
          "sanitizer.intervention.output_activated_desc",
          "Whether it was activated"
        )},
        "threat_type": {"type": "string", "description": t_modular(
          "sanitizer.intervention.output_threat_type_desc",
          "Primary threat type"
        )},
      },
    )

  async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
    """
    Generate a resistance response based on threats.

    Args:
      inputs: Dict with threats and severity

    Returns:
      Dict with response, activated, threat_type
    """
    threats: List[str] = inputs.get("threats", [])
    severity: str = inputs.get("severity", "medium")

    logger.warning(
      t_modular(
        "sanitizer.intervention.log_activated",
        "RESISTANCE ACTIVATED - Threats: {threats}, Severity: {severity}",
        threats=threats,
        severity=severity
      )
    )

    threat_type = threats[0] if threats else "unknown"

    response = RESISTANCE_RESPONSE

    return {
      "response": response,
      "activated": True,
      "threat_type": threat_type,
    }
