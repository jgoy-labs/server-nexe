"""
Tests per a F4 — CLI stop: PID file primer, fallback pgrep.

Verifica que `nexe stop` llegeix storage/run/server.pid si existeix,
i usa pgrep com a fallback si el PID file no existeix o el PID és mort.
"""
import json
import signal
from pathlib import Path
from unittest.mock import patch, MagicMock, call
from click.testing import CliRunner
from core.cli.cli import app


def _make_pid_file(tmp_path: Path, pid: int) -> Path:
    """Crea un PID file canònic amb el format esperat."""
    pid_dir = tmp_path / "storage" / "run"
    pid_dir.mkdir(parents=True)
    pid_file = pid_dir / "server.pid"
    pid_file.write_text(json.dumps({"pid": pid, "port": 9119, "started": "2026-04-09T10:00:00Z"}))
    return pid_file


class TestStopPidFilePrimary:
    """F4 — PID file canònic com a font primària."""

    def test_stop_reads_pid_file_and_sends_sigterm(self):
        """Si PID file existeix i PID és viu, SIGTERM al PID del fitxer (no pgrep)."""
        target_pid = 99999
        runner = CliRunner()

        with patch("os.kill") as mock_kill, \
             patch("subprocess.run") as mock_subproc, \
             patch("pathlib.Path.exists") as mock_exists, \
             patch("pathlib.Path.read_text") as mock_read_text, \
             patch("pathlib.Path.unlink"):

            # Simula: PID file existeix i PID és viu
            mock_exists.return_value = True
            mock_read_text.return_value = json.dumps({"pid": target_pid, "port": 9119})
            # kill(pid, 0) → procés viu (no excepció); kill(pid, SIGTERM) → OK
            mock_kill.return_value = None

            runner.invoke(app, ["stop", "--force"])

            # Ha d'haver cridat kill amb SIGTERM al target_pid
            sigterm_calls = [c for c in mock_kill.call_args_list if c == call(target_pid, signal.SIGTERM)]
            assert len(sigterm_calls) == 1, f"Expected SIGTERM to {target_pid}, got: {mock_kill.call_args_list}"
            # NO ha d'haver cridat pgrep
            assert mock_subproc.call_count == 0, "Should not use pgrep when PID file is valid"


class TestStopFallbackPgrep:
    """F4 — Fallback a pgrep quan PID file no existeix o PID és mort."""

    def test_stop_uses_pgrep_when_no_pid_file(self):
        """Sense PID file, ha de fer pgrep com a fallback."""
        runner = CliRunner()

        with patch("os.kill") as mock_kill, \
             patch("subprocess.run") as mock_subproc, \
             patch("pathlib.Path.exists") as mock_exists:

            # Simula: PID file no existeix
            mock_exists.return_value = False
            # pgrep retorna PID
            mock_pgrep = MagicMock()
            mock_pgrep.stdout = "12345\n"
            mock_subproc.return_value = mock_pgrep
            # kill OK
            mock_kill.return_value = None

            runner.invoke(app, ["stop", "--force"])

            # Ha d'haver cridat pgrep
            assert mock_subproc.called, "Should use pgrep when no PID file"
            pgrep_calls = [c for c in mock_subproc.call_args_list
                           if c.args and "pgrep" in c.args[0]]
            assert len(pgrep_calls) >= 1 or any("pgrep" in str(c) for c in mock_subproc.call_args_list)

    def test_stop_uses_pgrep_when_pid_is_dead(self):
        """Si PID file existeix però el PID és mort (ProcessLookupError), fallback a pgrep."""
        runner = CliRunner()

        with patch("os.kill") as mock_kill, \
             patch("subprocess.run") as mock_subproc, \
             patch("pathlib.Path.exists") as mock_exists, \
             patch("pathlib.Path.read_text") as mock_read_text, \
             patch("pathlib.Path.unlink"):

            # Simula: PID file existeix però el PID és mort
            mock_exists.return_value = True
            mock_read_text.return_value = json.dumps({"pid": 99998, "port": 9119})

            call_count = {"n": 0}

            def kill_side_effect(pid, sig):
                call_count["n"] += 1
                if sig == 0:
                    raise ProcessLookupError("No such process")
                return None

            mock_kill.side_effect = kill_side_effect

            # pgrep no troba res → no running
            mock_pgrep = MagicMock()
            mock_pgrep.stdout = ""
            mock_subproc.return_value = mock_pgrep

            runner.invoke(app, ["stop", "--force"])

            # pgrep ha de ser cridat (fallback)
            assert mock_subproc.called, "Should fall back to pgrep with dead PID"

    def test_stop_no_services_running(self):
        """Sense PID file ni pgrep hits → missatge informatiu."""
        runner = CliRunner()

        with patch("subprocess.run") as mock_subproc, \
             patch("pathlib.Path.exists") as mock_exists:

            mock_exists.return_value = False
            mock_pgrep = MagicMock()
            mock_pgrep.stdout = ""
            mock_subproc.return_value = mock_pgrep

            result = runner.invoke(app, ["stop", "--force"])

            assert "No Nexe services are running" in result.output
