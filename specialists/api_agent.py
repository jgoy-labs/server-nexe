"""
ApiAgent — Agent d'API per a server-nexe.
Detecta endpoints FastAPI via AST i avisa de breaking changes respecte al baseline.
Read-only absolut.
"""
import ast
from typing import Any, Dict, List, Set

from muthur.doctor.specialists.base_agent import BaseAgent

_HTTP_METHODS = {"get", "post", "put", "delete", "patch", "head", "options"}
_EXCLUDE_DIRS = {'.venv', 'venv', '__pycache__', '.git', 'node_modules', '.muthur', 'dist', 'build', 'bench'}


class ApiAgent(BaseAgent):
    """Agent d'API per server-nexe — detecta breaking changes d'endpoints."""

    @property
    def agent_name(self) -> str:
        return "api_agent"

    def diagnose(self) -> Dict[str, Any]:
        endpoints = self._scan_endpoints()
        ep_count = len(endpoints)

        baseline = self.memory.get_baseline()
        findings: List[Dict] = []
        memory_used = False
        new_issues = 0
        resolved_issues = 0

        if baseline is None:
            # Primer run: guardar baseline i retornar HEALTHY
            self.memory.set_baseline({"endpoints": endpoints})
            self.memory.save_run({"endpoints": endpoints, "findings": []})
            reasoning = (
                f"He analitzat {ep_count} endpoints via AST (decoradors FastAPI) "
                f"a {self.project_path.name}. Primer run: baseline guardat."
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

        # Runs successius: comparar amb baseline
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
                "message": f"Endpoint eliminat: {ep}",
            })

        new_issues = len(findings)
        resolved_issues = 0  # Endpoints nous (added) no son problemes resolts — son features

        status = "UNHEALTHY" if findings else "HEALTHY"

        reasoning = (
            f"He analitzat {ep_count} endpoints via AST a {self.project_path.name}. "
            f"He comparat amb el baseline: {len(removed)} eliminats, {len(added)} nous."
        )

        self.memory.save_run({"endpoints": endpoints, "findings": findings})

        return {
            "status": status,
            "findings": findings,
            "reasoning": reasoning,
            "top_offenders": [f["id"].replace("api:removed:", "") for f in findings[:5]],
            "recommendations": ["Verificar backward compatibility"] if findings else [],
            "memory_used": memory_used,
            "new_issues": new_issues,
            "resolved_issues": resolved_issues,
        }

    def _scan_endpoints(self) -> List[str]:
        """Detecció estàtica via AST: @router.get('/path'), @app.post('/path')."""
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
        """Extreu 'METHOD /path' d'un decorador FastAPI si és vàlid."""
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
