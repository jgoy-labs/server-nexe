"""
PluginAgent — Agent de plugins per a server-nexe.
Valida el contracte de cada plugin (estructura mínima) i detecta regressions.
Read-only absolut.
"""
from pathlib import Path
from typing import Any, Dict, List

from muthur.doctor.specialists.base_agent import BaseAgent

_REQUIRED_FILES = ("__init__.py",)


class PluginAgent(BaseAgent):
    """Agent de plugins per server-nexe — valida contractes i detecta regressions."""

    @property
    def agent_name(self) -> str:
        return "plugin_agent"

    def diagnose(self) -> Dict[str, Any]:
        plugins_dir = self.project_path / "plugins"
        if not plugins_dir.exists():
            return {
                "status": "HEALTHY",
                "findings": [],
                "reasoning": f"No s'ha trobat carpeta plugins/ a {self.project_path.name}. No hi ha plugins a validar.",
                "top_offenders": [],
                "recommendations": [],
                "memory_used": False,
                "new_issues": 0,
                "resolved_issues": 0,
            }

        plugins = [d for d in plugins_dir.iterdir() if d.is_dir() and not d.name.startswith('_')]
        findings: List[Dict] = []
        top_offenders: List[str] = []

        for plugin_dir in plugins:
            plugin_findings = self._validate_plugin(plugin_dir)
            if plugin_findings:
                findings.extend(plugin_findings)
                top_offenders.append(plugin_dir.name)

        compare = self._compare_with_last_run(findings)

        status = "UNHEALTHY" if findings else "HEALTHY"
        if findings and compare["memory_used"] and compare["new_issues"] == 0:
            status = "DEGRADED"

        reasoning = (
            f"He analitzat {len(plugins)} plugins a {self.project_path.name}/plugins/ "
            f"verificant contracte mínim ({', '.join(_REQUIRED_FILES)})."
        )
        if compare["memory_used"]:
            reasoning += (
                f" He comparat amb el run anterior: {compare['new_issues']} nous problemes,"
                f" {compare['resolved_issues']} resolts."
            )

        self.memory.save_run({"plugins": [p.name for p in plugins], "findings": findings})

        return {
            "status": status,
            "findings": findings,
            "reasoning": reasoning,
            "top_offenders": top_offenders[:5],
            "recommendations": self._build_recommendations(findings),
            "memory_used": compare["memory_used"],
            "new_issues": compare["new_issues"],
            "resolved_issues": compare["resolved_issues"],
        }

    def _validate_plugin(self, plugin_dir: Path) -> List[Dict]:
        findings = []
        for required in _REQUIRED_FILES:
            if not (plugin_dir / required).exists():
                findings.append({
                    "id": f"plugin:{plugin_dir.name}:missing:{required}",
                    "severity": "high",
                    "type": "plugin_contract_violation",
                    "plugin": plugin_dir.name,
                    "message": f"Plugin '{plugin_dir.name}' sense {required}",
                })
        return findings

    def _build_recommendations(self, findings: List[Dict]) -> List[str]:
        if not findings:
            return []
        return [
            "Afegir __init__.py a cada plugin per garantir el contracte de paquet Python",
            "Considerar afegir manifest.toml per metadades del plugin",
        ]
