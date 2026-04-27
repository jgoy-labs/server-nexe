"""
SecurityAgent — Agent de seguretat per a server-nexe.
Detecta secrets exposats, patterns JWT i problemes d'autenticació.
Read-only absolut: no modifica cap fitxer del target.
"""
import ast
import re
from pathlib import Path
from typing import Any, Dict, List

from muthur.doctor.specialists.base_agent import BaseAgent

_SECRET_PATTERNS = re.compile(
    r'(?i)(api[_-]?key|secret[_-]?key|jwt[_-]?secret|password|token|auth[_-]?key)'
    r'\s*=\s*["\'][^"\']{8,}["\']'
)

_EXCLUDE_DIRS = {'.venv', 'venv', '__pycache__', '.git', 'node_modules', '.muthur', 'dist', 'build', 'bench'}


class SecurityAgent(BaseAgent):
    """Agent de seguretat per server-nexe — sap que usa FastAPI + JWT."""

    @property
    def agent_name(self) -> str:
        return "security_agent"

    def diagnose(self) -> Dict[str, Any]:
        findings: List[Dict] = []
        py_files_scanned = 0
        top_offenders: List[str] = []

        for py_file in self._iter_python_files():
            py_files_scanned += 1
            file_findings = self._scan_file(py_file)
            if file_findings:
                findings.extend(file_findings)
                top_offenders.append(str(py_file.relative_to(self.project_path)))

        compare = self._compare_with_last_run(findings)

        if findings:
            status = "UNHEALTHY" if any(f["severity"] == "high" for f in findings) else "DEGRADED"
        else:
            status = "HEALTHY"

        skipped_note = ""
        try:
            total = sum(1 for _ in self._iter_python_files())
            if total != py_files_scanned:
                skipped_note = f" ({total - py_files_scanned} fitxers saltats per errors)"
        except Exception:
            pass

        reasoning = (
            f"He analitzat {py_files_scanned} fitxers Python via regex de patterns secrets/JWT/auth"
            f" a {self.project_path.name}.{skipped_note}"
        )
        if compare["memory_used"]:
            reasoning += (
                f" He comparat amb el run anterior: {compare['new_issues']} nous problemes,"
                f" {compare['resolved_issues']} resolts."
            )

        run_data = {"findings": findings, "status": status}
        self.memory.save_run(run_data)

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

    def _iter_python_files(self):
        for d in self.project_path.iterdir():
            if d.is_dir() and d.name not in _EXCLUDE_DIRS and not d.name.startswith('.'):
                yield from d.rglob("*.py")
        yield from self.project_path.glob("*.py")

    def _scan_file(self, py_file: Path) -> List[Dict]:
        findings = []
        try:
            content = py_file.read_text(encoding="utf-8", errors="ignore")
            for match in _SECRET_PATTERNS.finditer(content):
                line_num = content[:match.start()].count('\n') + 1
                rel_path = str(py_file.relative_to(self.project_path))
                findings.append({
                    "id": f"secret:{rel_path}:{line_num}",
                    "severity": "high",
                    "type": "hardcoded_secret",
                    "file": rel_path,
                    "line": line_num,
                    "message": f"Possible secret hardcoded: {match.group()[:60]}",
                })
        except (OSError, UnicodeDecodeError):
            pass
        return findings

    def _build_recommendations(self, findings: List[Dict]) -> List[str]:
        if not findings:
            return []
        return [
            "Moure secrets a variables d'entorn o .env",
            "Usar un gestor de secrets (Vault, AWS Secrets Manager)",
            "Revisar git history per assegurar que no s'han commitejat",
        ]
