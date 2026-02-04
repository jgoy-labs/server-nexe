"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: plugins/security/sanitizer/workflow/nodes/resistencia_node.py
Description: Node de Intervenció - Resposta predefinida quan es detecta jailbreak.

www.jgoy.net
────────────────────────────────────
"""

import logging
from typing import Any, Dict, List

from nexe_flow.core.node import Node, NodeMetadata

logger = logging.getLogger(__name__)

RESISTANCE_RESPONSE = "Crec que hi ha un problema amb el teu missatge. Pots reformular?"

class InterventionNode(Node):
  """
  Node de Intervenció per a Nexe.

  Quan el Sanitizer detecta amenaces, aquest node:
  1. Genera una resposta de resistència adequada
  2. Atura el pipeline (és terminal)
  3. No crida el LLM (estalvia recursos i evita riscos)

  Inputs:
    threats: List[str] - Llista d'amenaces detectades pel Sanitizer
    severity: str - Nivell de severitat ("low", "medium", "high", "critical")

  Outputs:
    response: str - Resposta de resistència
    activated: bool - True (sempre, si s'executa)
    threat_type: str - Tipus principal d'amenaça
  """

  def get_metadata(self) -> NodeMetadata:
    return NodeMetadata(
      node_type="intervention.respond",
      version="1.0.0",
      description="Genera resposta de resistència quan es detecten amenaces",
      inputs={
        "threats": {
          "type": "array",
          "description": "Llista d'amenaces detectades",
          "required": False,
          "default": [],
        },
        "severity": {
          "type": "string",
          "description": "Nivell de severitat",
          "required": False,
          "default": "medium",
        },
      },
      outputs={
        "response": {"type": "string", "description": "Resposta de resistència"},
        "activated": {"type": "boolean", "description": "Si s'ha activat"},
        "threat_type": {"type": "string", "description": "Tipus d'amenaça principal"},
      },
    )

  async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
    """
    Genera resposta de resistència basada en les amenaces.

    Args:
      inputs: Dict amb threats i severity

    Returns:
      Dict amb response, activated, threat_type
    """
    threats: List[str] = inputs.get("threats", [])
    severity: str = inputs.get("severity", "medium")

    logger.warning(
      "RESISTÈNCIA ACTIVADA - Threats: %s, Severity: %s",
      threats, severity
    )

    threat_type = threats[0] if threats else "unknown"

    response = RESISTANCE_RESPONSE

    return {
      "response": response,
      "activated": True,
      "threat_type": threat_type,
    }