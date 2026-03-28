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
  """Configuracio del node SANITIZER."""
  fail_on_critical: bool = False
  enable_telemetry: bool = True

class SanitizerNode(Node):
  """
  Node de workflow per SANITIZER (seguretat TECNICA).

  Detecta jailbreaks i prompt injections.
  NO bloqueja (graceful degradation), nomes marca i avisa.

  Inputs esperats:
  - text: str - Text a sanititzar
  - user_message: str - Alias per text (compatibilitat)

  Outputs:
  - is_safe: bool - True si no hi ha amenaces critiques
  - needs_intervention: bool - True si Auditor ha d'activar Intervenció
  - severity: str - "none" | "low" | "medium" | "high" | "critical"
  - threats: List[str] - Amenaces detectades
  - clean_text: str - Text processat (igual a input)
  - scan_time_ms: float - Temps d'escaneig

  Filosofia Graceful Degradation:
  - severity != critical -> continua (is_safe=True)
  - severity == critical -> OPCIONALMENT bloqueja (configurable)
  - needs_intervention -> Auditor activa Intervenció
  """

  def __init__(self, config: Optional[SanitizerNodeConfig] = None):
    self.config = config or SanitizerNodeConfig()
    self._sanitizer = get_sanitizer()
    super().__init__()

  def get_metadata(self) -> NodeMetadata:
    """Retorna el metadata del node SANITIZER."""
    return NodeMetadata(
      id="sanitizer.check",
      name="SANITIZER Check",
      version="1.0.0",
      description="Detecta jailbreaks i prompt injections (seguretat TECNICA)",
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
        NodeOutput(name="scan_time_ms", type="number", description="Temps d'escaneig en ms"),
      ],
      icon="🛡️",
      color="#e74c3c"
    )

  async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
    """
    Executa el node SANITIZER.

    Temps objectiu: <2ms
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