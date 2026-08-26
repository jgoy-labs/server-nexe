"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/test_837_ollama_linux_no_sudo.py
Description: #837 — on Linux without non-interactive sudo, the official
            install.sh dies on its own inner `sudo` with "a terminal is
            required to read the password". Reproduced live on 2026-08-26
            with NOPASSWD disabled: the user got a warning followed by an
            empty line and no way forward. The installer must now detect the
            condition up front and print the exact manual command instead.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
from unittest.mock import MagicMock

import installer.installer_ollama_install as oi


def _capture_output(monkeypatch):
    lines: list[str] = []
    monkeypatch.setattr(oi, "print_warn", lambda m: lines.append(str(m)))
    monkeypatch.setattr("builtins.print", lambda *a, **k: lines.append(" ".join(str(x) for x in a)))
    return lines


def test_no_sudo_refuses_before_running_the_script(monkeypatch):
    """The live failure mode: no root reachable → never run install.sh."""
    monkeypatch.setattr(oi, "_linux_can_reach_root", lambda: False)
    ran = []
    monkeypatch.setattr(oi.subprocess, "run", lambda *a, **k: ran.append(a) or MagicMock(returncode=0))
    lines = _capture_output(monkeypatch)

    assert oi._install_ollama_linux() is False
    assert ran == [], "must not download or execute install.sh without root"
    assert any("install.sh" in ln and "curl" in ln for ln in lines), (
        f"the user must be told the exact manual command; got: {lines}"
    )


def test_with_sudo_the_install_still_proceeds(monkeypatch):
    """No over-blocking: root reachable → the normal install path runs."""
    import hashlib

    monkeypatch.setattr(oi, "_linux_can_reach_root", lambda: True)
    # curl is mocked, so the tempfile stays empty — pin to the hash of b"".
    monkeypatch.setattr(
        oi, "_resolve_ollama_pin", lambda k: (hashlib.sha256(b"").hexdigest(), None, None)
    )

    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return MagicMock(returncode=0)

    monkeypatch.setattr(oi.subprocess, "run", fake_run)
    monkeypatch.setattr(oi, "print_success", lambda *a, **k: None)
    _capture_output(monkeypatch)

    assert oi._install_ollama_linux() is True
    assert any(c[0] == "bash" for c in calls), f"install.sh must be executed; got {calls}"


def test_failed_script_still_tells_the_user_what_to_run(monkeypatch):
    """The mute failure: returncode!=0 printed a warning and nothing else."""
    monkeypatch.setattr(oi, "_linux_can_reach_root", lambda: True)
    import hashlib
    monkeypatch.setattr(oi, "_resolve_ollama_pin", lambda k: (hashlib.sha256(b"").hexdigest(), None, None))
    monkeypatch.setattr(oi.subprocess, "run", lambda *a, **k: MagicMock(returncode=1))
    lines = _capture_output(monkeypatch)

    assert oi._install_ollama_linux() is False
    assert any("install.sh" in ln and "curl" in ln for ln in lines), (
        f"a failed install must still print the manual command; got: {lines}"
    )


def test_root_needs_no_sudo(monkeypatch):
    """Running as root: no sudo probe at all."""
    monkeypatch.setattr(oi.os, "geteuid", lambda: 0)
    probed = []
    monkeypatch.setattr(oi.subprocess, "run", lambda *a, **k: probed.append(a) or MagicMock(returncode=1))
    assert oi._linux_can_reach_root() is True
    assert probed == [], "root must not shell out to sudo"


def test_missing_sudo_binary_is_not_root(monkeypatch):
    monkeypatch.setattr(oi.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(oi.shutil, "which", lambda name: None)
    assert oi._linux_can_reach_root() is False


def test_passwordless_sudo_detected(monkeypatch):
    """`sudo -n true` decides — exactly what the live test toggled."""
    monkeypatch.setattr(oi.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(oi.shutil, "which", lambda name: "/usr/bin/sudo")
    monkeypatch.setattr(oi.subprocess, "run", lambda *a, **k: MagicMock(returncode=0))
    assert oi._linux_can_reach_root() is True

    monkeypatch.setattr(oi.subprocess, "run", lambda *a, **k: MagicMock(returncode=1))
    assert oi._linux_can_reach_root() is False
