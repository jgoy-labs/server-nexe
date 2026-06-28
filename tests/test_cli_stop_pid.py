"""
Tests for F4 — CLI stop: PID file first, pgrep fallback.

Verifies that `nexe stop` reads storage/run/server.pid if it exists,
and uses pgrep as fallback if the PID file does not exist or the PID is dead.
"""
import json
import signal
from pathlib import Path
from unittest.mock import patch, MagicMock, call
from click.testing import CliRunner
from core.cli.cli import app


def _make_pid_file(tmp_path: Path, pid: int) -> Path:
    """Creates a canonical PID file with the expected format."""
    pid_dir = tmp_path / "storage" / "run"
    pid_dir.mkdir(parents=True)
    pid_file = pid_dir / "server.pid"
    pid_file.write_text(json.dumps({"pid": pid, "port": 9119, "started": "2026-04-09T10:00:00Z"}))
    return pid_file


class TestStopPidFilePrimary:
    """F4 — Canonical PID file as primary source."""

    def test_stop_reads_pid_file_and_sends_sigterm(self):
        """If PID file exists and PID is alive, send SIGTERM to the file's PID (not pgrep)."""
        target_pid = 99999
        runner = CliRunner()

        with patch("os.kill") as mock_kill, \
             patch("subprocess.run") as mock_subproc, \
             patch("pathlib.Path.exists") as mock_exists, \
             patch("pathlib.Path.read_text") as mock_read_text, \
             patch("pathlib.Path.unlink"):

            # Simulate: PID file exists and PID is alive
            mock_exists.return_value = True
            mock_read_text.return_value = json.dumps({"pid": target_pid, "port": 9119})
            # kill(pid, 0) → process alive (no exception); kill(pid, SIGTERM) → OK
            mock_kill.return_value = None

            runner.invoke(app, ["stop", "--force"])

            # Must have called kill with SIGTERM to target_pid
            sigterm_calls = [c for c in mock_kill.call_args_list if c == call(target_pid, signal.SIGTERM)]
            assert len(sigterm_calls) == 1, f"Expected SIGTERM to {target_pid}, got: {mock_kill.call_args_list}"
            # Must NOT have called pgrep
            assert mock_subproc.call_count == 0, "Should not use pgrep when PID file is valid"


class TestStopFallbackPgrep:
    """F4 — Fallback to pgrep when PID file does not exist or PID is dead."""

    def test_stop_uses_pgrep_when_no_pid_file(self):
        """Without PID file, must use pgrep as fallback."""
        runner = CliRunner()

        with patch("os.kill") as mock_kill, \
             patch("subprocess.run") as mock_subproc, \
             patch("pathlib.Path.exists") as mock_exists:

            # Simulate: PID file does not exist
            mock_exists.return_value = False
            # pgrep returns PID
            mock_pgrep = MagicMock()
            mock_pgrep.stdout = "12345\n"
            mock_subproc.return_value = mock_pgrep
            # kill OK
            mock_kill.return_value = None

            runner.invoke(app, ["stop", "--force"])

            # Must have called pgrep
            assert mock_subproc.called, "Should use pgrep when no PID file"
            pgrep_calls = [c for c in mock_subproc.call_args_list
                           if c.args and "pgrep" in c.args[0]]
            assert len(pgrep_calls) >= 1 or any("pgrep" in str(c) for c in mock_subproc.call_args_list)

    def test_stop_uses_pgrep_when_pid_is_dead(self):
        """If PID file exists but the PID is dead (ProcessLookupError), fall back to pgrep."""
        runner = CliRunner()

        with patch("os.kill") as mock_kill, \
             patch("subprocess.run") as mock_subproc, \
             patch("pathlib.Path.exists") as mock_exists, \
             patch("pathlib.Path.read_text") as mock_read_text, \
             patch("pathlib.Path.unlink"):

            # Simulate: PID file exists but the PID is dead
            mock_exists.return_value = True
            mock_read_text.return_value = json.dumps({"pid": 99998, "port": 9119})

            call_count = {"n": 0}

            def kill_side_effect(pid, sig):
                call_count["n"] += 1
                if sig == 0:
                    raise ProcessLookupError("No such process")
                return None

            mock_kill.side_effect = kill_side_effect

            # pgrep finds nothing → not running
            mock_pgrep = MagicMock()
            mock_pgrep.stdout = ""
            mock_subproc.return_value = mock_pgrep

            runner.invoke(app, ["stop", "--force"])

            # pgrep must be called (fallback)
            assert mock_subproc.called, "Should fall back to pgrep with dead PID"

    def test_stop_no_services_running(self):
        """Without PID file or pgrep hits → informational message."""
        runner = CliRunner()

        with patch("subprocess.run") as mock_subproc, \
             patch("pathlib.Path.exists") as mock_exists:

            mock_exists.return_value = False
            mock_pgrep = MagicMock()
            mock_pgrep.stdout = ""
            mock_subproc.return_value = mock_pgrep

            result = runner.invoke(app, ["stop", "--force"])

            # NEXE_LANG-aware: accepts output in Catalan or English (audit r1 P1).
            assert (
                "No Nexe services are running" in result.output
                or "Cap servei Nexe actiu" in result.output
            ), f"Output inesperat: {result.output!r}"


class TestPgrepPatternMatchesRealProcess:
    """B109 — el patró pgrep ha de casar amb el cmdline real de llançament,
    no amb 'uvicorn.*nexe' (que mai apareix al cmdline)."""

    # cmdlines reals possibles del servidor viu:
    #  - abans del setproctitle: 'python -m core.app' (cli.py:184)
    #  - després del setproctitle: 'server-nexe' (runner.py:201)
    REAL_CMDLINES = [
        "/usr/bin/python3 -m core.app",
        "server-nexe",
    ]

    def _capture_pattern(self):
        import re  # noqa: F401  (usat als mètodes que el criden)
        from core.cli.cli import _stop_find_via_pgrep
        captured = {}

        def fake_run(cmd, *a, **k):
            captured["cmd"] = cmd
            m = MagicMock()
            m.stdout = ""  # 0 PIDs: només volem capturar el patró
            return m

        with patch("subprocess.run", side_effect=fake_run):
            _stop_find_via_pgrep()
        return captured["cmd"]

    def test_pgrep_invoked_with_f_flag(self):
        cmd = self._capture_pattern()
        assert cmd[0] == "pgrep" and cmd[1] == "-f"

    def test_pgrep_pattern_matches_a_real_server_cmdline(self):
        import re
        cmd = self._capture_pattern()
        pattern = cmd[2]
        matched = any(re.search(pattern, cl) for cl in self.REAL_CMDLINES)
        assert matched, (
            f"El patró pgrep {pattern!r} no casa amb cap cmdline real "
            f"del servidor {self.REAL_CMDLINES!r}; 'nexe stop' no trobarà el procés."
        )

    def test_pgrep_pattern_is_not_the_phantom_uvicorn(self):
        cmd = self._capture_pattern()
        assert "uvicorn" not in cmd[2], (
            "El patró encara busca 'uvicorn', que mai apareix al cmdline "
            "(es llança 'python -m core.app' i setproctitle='server-nexe')."
        )


class TestStopPermissionDenied:
    """B111 — no s'ha de reportar 'Services stopped' si tots els SIGTERM fallen per permisos."""

    def test_stop_no_false_success_on_permission_denied(self):
        import os
        target_pid = 99999
        runner = CliRunner()
        with patch.dict(os.environ, {"NEXE_LANG": "en-US"}), \
             patch("os.kill") as mock_kill, \
             patch("subprocess.run") as mock_subproc, \
             patch("pathlib.Path.exists") as mock_exists, \
             patch("pathlib.Path.read_text") as mock_read_text, \
             patch("pathlib.Path.unlink"):
            mock_exists.return_value = True
            mock_read_text.return_value = json.dumps({"pid": target_pid, "port": 9119})

            def kill_side_effect(pid, sig):
                if sig == 0:
                    return None  # PID viu (comprovació del PID-file)
                raise PermissionError("Operation not permitted")  # SIGTERM denegat
            mock_kill.side_effect = kill_side_effect
            mock_subproc.return_value = type("R", (), {"stdout": ""})()

            result = runner.invoke(app, ["stop", "--force"])

        assert "permission denied" in result.output, result.output
        assert "Services stopped" not in result.output, (
            f"Fals èxit reportat malgrat PermissionError: {result.output!r}")
        assert call(target_pid, signal.SIGTERM) in mock_kill.call_args_list
