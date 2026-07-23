"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/proc_utils.py
Description: Cross-platform subprocess creation-flag helpers.

             On Windows a GUI app (the Tauri shell, which has no console) that
             spawns a console child — curl, ollama.exe, taskkill … — pops a
             visible console window unless CREATE_NO_WINDOW is set. These helpers
             return the right kwargs per platform so call sites stay one-liners
             and no console flashes during onboarding or runtime. On POSIX there
             is no such concept, so they are no-ops (or preserve the existing
             start_new_session for detached daemons).

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from __future__ import annotations

import sys

# subprocess exposes these creation flags only on Windows, so we define them
# locally to keep this module importable on every platform.
_CREATE_NO_WINDOW = 0x0800_0000
_DETACHED_PROCESS = 0x0000_0008          # ⚠️ makes Windows IGNORE CREATE_NO_WINDOW
_CREATE_NEW_PROCESS_GROUP = 0x0000_0200  # Ctrl-C isolation WITHOUT defeating no-window


def no_window_kwargs() -> dict:
    """Popen / run / create_subprocess_exec kwargs that suppress the console
    window on Windows for a *blocking* child (its stdout/stderr may be captured).

    Returns ``{}`` on POSIX (no console-window concept there).
    """
    if sys.platform == "win32":
        return {"creationflags": _CREATE_NO_WINDOW}
    return {}


def detached_kwargs() -> dict:
    """Like :func:`no_window_kwargs` but for a *daemon* that must outlive its
    parent (e.g. ``ollama serve``).

    * Windows: ``CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP`` — no window + its
      own process group (isolated from the parent's Ctrl-C). We do NOT use
      DETACHED_PROCESS: per MSDN, CREATE_NO_WINDOW is IGNORED when combined with
      DETACHED_PROCESS, so the daemon (``ollama serve``) would pop a VISIBLE
      console — the exact "terminals flashing" bug the 06/07 fix missed.
    * POSIX: ``start_new_session=True`` — the long-standing behaviour (own
      session/process group so shutdown can signal the whole group).
    """
    if sys.platform == "win32":
        return {"creationflags": _CREATE_NO_WINDOW | _CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}
