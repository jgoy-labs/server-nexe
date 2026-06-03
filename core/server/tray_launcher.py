"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/server/tray_launcher.py
Description: macOS tray launch/cleanup logic extracted from core/server/runner.py
. Detects tray support, kills stale tray processes and
             launches a fresh tray (NexeTray.app bundle or python -m fallback).

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

logger = logging.getLogger(__name__)


def _is_tray_already_running() -> bool:
    """Return True if NEXE_TRAY_PID is set (server was launched from the tray)."""
    if os.environ.get("NEXE_TRAY_PID"):
        logger.debug("Tray already running (NEXE_TRAY_PID set) — skipping tray launch")
        return True
    return False


def _is_tray_supported() -> bool:
    """Return True if all conditions for tray launch are met."""
    # Tauri already manages the tray when running in sidecar mode
    # (ADR-tray-doble-conflicte) — evitem doble icona Python + Tauri.
    if os.environ.get("NEXE_SIDECAR"):
        return False
    if sys.platform != "darwin":
        return False
    if os.environ.get("NEXE_DOCKER") or os.environ.get("CONTAINER"):
        return False
    if os.environ.get("NEXE_NO_TRAY"):
        return False
    try:
        import rumps  # noqa: F401
    except ImportError:
        logger.debug("rumps not installed — tray not available")
        return False
    return True


def _kill_stale_tray() -> None:
    """Kill any stale tray processes before launching a fresh one."""
    try:
        stale_pids: list[int] = []
        for pattern in ("installer.tray", "nexe-tray", "NexeTray"):
            result = subprocess.run(  # nosec B603 B607: pattern from local literal tuple ("installer.tray", "nexe-tray", "NexeTray"); pgrep via PATH
                ["pgrep", "-f", pattern],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                stale_pids += [int(p) for p in result.stdout.strip().split('\n') if p.strip()]
        stale_pids = list(set(stale_pids))
        if stale_pids:
            for pid in stale_pids:
                try:
                    os.kill(pid, signal.SIGTERM)
                except (ProcessLookupError, PermissionError):
                    pass
            time.sleep(1)
            for pid in stale_pids:
                try:
                    os.kill(pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
            time.sleep(0.3)
            logger.debug("Killed stale tray process(es) — launching fresh one")
    except Exception:  # nosec B110: best-effort cleanup; if it fails the fresh tray launch still proceeds
        pass


def _launch_tray_process(project_root: Path) -> None:
    """Launch the tray process, preferring the NexeTray.app bundle over python -m."""
    venv_python = project_root / "venv" / "bin" / "python"
    python_exe = str(venv_python) if venv_python.exists() else sys.executable

    server_pid = os.getpid()
    tray_args = ["--attach", "--server-pid", str(server_pid)]
    tray_binary = project_root / "installer" / "NexeTray.app" / "Contents" / "MacOS" / "NexeTray"

    try:
        if tray_binary.exists():
            subprocess.Popen(  # nosec B603: tray_binary is project_root-derived absolute Path; tray_args is local literal list
                [str(tray_binary)] + tray_args,
                cwd=str(project_root),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            logger.info("Tray launched via bundle (server PID %d)", server_pid)
        else:
            subprocess.Popen(  # nosec B603: python_exe is venv_python absolute Path or sys.executable fallback; tray_args is local literal list
                [python_exe, "-m", "installer.tray"] + tray_args,
                cwd=str(project_root),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            logger.info("Tray launched via python -m (dev fallback, server PID %d)", server_pid)
    except Exception as e:
        logger.warning("Could not launch tray: %s", e)


def _maybe_launch_tray(_project_root: "Path | None" = None):
    """Launch the macOS tray icon if on macOS and no tray is already running.

    Args:
        _project_root: Override project root (tests only). If None, derived from __file__.
    """
    if _is_tray_already_running():
        return
    if not _is_tray_supported():
        return
    _kill_stale_tray()
    project_root = _project_root if _project_root is not None else Path(__file__).resolve().parent.parent
    _launch_tray_process(project_root)
