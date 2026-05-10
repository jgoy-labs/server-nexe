"""
ApiAgent — API agent for server-nexe.
Detects FastAPI endpoints via AST and warns of breaking changes against the baseline.
Strictly read-only.
"""
import ast
from typing import Any, Dict, List, Set

from muthur.doctor.specialists.base_agent import BaseAgent

_HTTP_METHODS = {"get", "post", "put", "delete", "patch", "head", "options"}
_EXCLUDE_DIRS = {'.venv', 'venv', '__pycache__', '.git', 'node_modules', '.muthur', 'dist', 'build', 'bench'}


class ApiAgent(BaseAgent):
    """API agent for server-nexe — detects endpoint breaking changes."""

    @property
    def agent_name(self) -> str:
        """Return the unique identifier for this agent."""
        return "api_agent"

    def diagnose(self) -> Dict[str, Any]:
        """Scan FastAPI endpoints via AST and compare against the stored baseline."""
        endpoints = self._scan_endpoints()
        ep_count = len(endpoints)

        baseline = self.memory.get_baseline()
        findings: List[Dict] = []
        memory_used = False
        new_issues = 0
        resolved_issues = 0

        if baseline is None:
            # First run: save baseline and return HEALTHY
            self.memory.set_baseline({"endpoints": endpoints})
            self.memory.save_run({"endpoints": endpoints, "findings": []})
            reasoning = (
                f"Analysed {ep_count} endpoints via AST (FastAPI decorators) "
                f"in {self.project_path.name}. First run: baseline saved."
            )
            return {
                "status": "HEALTHY",
                "findings": [],
                "reasoning": reasoning,
                "top_offenders": [],
                "recommendations": [],
                "memory_used": False,
                "new_issues": 0,
                "resolved_issues": 0,
            }

        # Successive runs: compare against baseline
        memory_used = True
        baseline_eps: Set[str] = set(baseline.get("endpoints", []))
        current_eps: Set[str] = set(endpoints)

        removed = baseline_eps - current_eps
        added = current_eps - baseline_eps

        for ep in removed:
            findings.append({
                "id": f"api:removed:{ep}",
                "severity": "high",
                "type": "breaking_change",
                "message": f"Endpoint removed: {ep}",
            })

        new_issues = len(findings)
        resolved_issues = 0  # New endpoints (added) are not resolved issues — they are features

        status = "UNHEALTHY" if findings else "HEALTHY"

        reasoning = (
            f"Analysed {ep_count} endpoints via AST in {self.project_path.name}. "
            f"Compared against baseline: {len(removed)} removed, {len(added)} new."
        )

        self.memory.save_run({"endpoints": endpoints, "findings": findings})

        return {
            "status": status,
            "findings": findings,
            "reasoning": reasoning,
            "top_offenders": [f["id"].replace("api:removed:", "") for f in findings[:5]],
            "recommendations": ["Verify backward compatibility"] if findings else [],
            "memory_used": memory_used,
            "new_issues": new_issues,
            "resolved_issues": resolved_issues,
        }

    def _scan_endpoints(self) -> List[str]:
        """Static detection via AST: @router.get('/path'), @app.post('/path')."""
        endpoints = []
        for py_file in self._iter_python_files():
            try:
                source = py_file.read_text(encoding="utf-8", errors="ignore")
                tree = ast.parse(source, filename=str(py_file))
                for node in ast.walk(tree):
                    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        continue
                    for dec in node.decorator_list:
                        ep = self._extract_endpoint(dec)
                        if ep:
                            endpoints.append(ep)
            except (SyntaxError, OSError):
                pass
        return sorted(set(endpoints))

    def _extract_endpoint(self, decorator) -> str:
        """Extracts 'METHOD /path' from a FastAPI decorator if valid."""
        if not isinstance(decorator, ast.Call):
            return ""
        func = decorator.func
        if isinstance(func, ast.Attribute):
            method = func.attr.lower()
        else:
            return ""
        if method not in _HTTP_METHODS:
            return ""
        if decorator.args and isinstance(decorator.args[0], ast.Constant):
            path = decorator.args[0].value
            if not isinstance(path, str):
                return ""
            return f"{method.upper()} {path}"
        return ""

    def _iter_python_files(self):
        for d in self.project_path.iterdir():
            if d.is_dir() and d.name not in _EXCLUDE_DIRS and not d.name.startswith('.'):
                yield from d.rglob("*.py")
        yield from self.project_path.glob("*.py")
