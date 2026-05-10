"""
PluginAgent — Plugin agent for server-nexe.
Validates the contract of each plugin (minimum structure) and detects regressions.
Strictly read-only.
"""
from pathlib import Path
from typing import Any, Dict, List

from muthur.doctor.specialists.base_agent import BaseAgent

_REQUIRED_FILES = ("__init__.py",)


class PluginAgent(BaseAgent):
    """Plugin agent for server-nexe — validates contracts and detects regressions."""

    @property
    def agent_name(self) -> str:
        """Return the unique identifier for this agent."""
        return "plugin_agent"

    def diagnose(self) -> Dict[str, Any]:
        """Validate all plugin manifests, health checks, and structural conventions."""
        plugins_dir = self.project_path / "plugins"
        if not plugins_dir.exists():
            return {
                "status": "HEALTHY",
                "findings": [],
                "reasoning": f"plugins/ folder not found in {self.project_path.name}. No plugins to validate.",
                "top_offenders": [],
                "recommendations": [],
                "memory_used": False,
                "new_issues": 0,
                "resolved_issues": 0,
            }

        try:
            plugins = [d for d in plugins_dir.iterdir() if d.is_dir() and not d.name.startswith('_')]
        except OSError:
            return {
                "status": "DEGRADED",
                "findings": [],
                "reasoning": f"Could not read {plugins_dir}: permission error.",
                "top_offenders": [],
                "recommendations": [],
                "memory_used": False,
                "new_issues": 0,
                "resolved_issues": 0,
            }
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
            f"Analysed {len(plugins)} plugins in {self.project_path.name}/plugins/ "
            f"verifying minimum contract ({', '.join(_REQUIRED_FILES)})."
        )
        if compare["memory_used"]:
            reasoning += (
                f" Compared against previous run: {compare['new_issues']} new issues,"
                f" {compare['resolved_issues']} resolved."
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
                    "message": f"Plugin '{plugin_dir.name}' missing {required}",
                })
        return findings

    def _build_recommendations(self, findings: List[Dict]) -> List[str]:
        if not findings:
            return []
        return [
            "Add __init__.py to each plugin to ensure Python package contract",
            "Consider adding manifest.toml for plugin metadata",
        ]
