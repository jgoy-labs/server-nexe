"""
────────────────────────────────────
Server Nexe
Location: installer/tray_uninstaller.py
Description: Uninstall logic for the tray app.
────────────────────────────────────
"""

import platform
import shutil
import subprocess
from pathlib import Path


def _format_bytes(b):
    """Format bytes as human-readable string."""
    if b < 1024 ** 2:
        return f"{b / 1024:.0f} KB"
    if b < 1024 ** 3:
        return f"{b / (1024 ** 2):.1f} MB"
    return f"{b / (1024 ** 3):.2f} GB"


def calculate_storage(install_dir: Path) -> str:
    """Calculate total disk usage of the Nexe installation."""
    total = 0
    for path in [install_dir, Path("/Applications/Nexe.app")]:
        if path.exists():
            try:
                for f in path.rglob("*"):
                    if f.is_file() and not f.is_symlink():
                        try:
                            total += f.stat().st_size
                        except OSError:
                            pass
            except OSError:
                pass
    return _format_bytes(total) if total > 0 else "—"


def remove_from_dock() -> bool:
    """Remove Nexe.app from the macOS Dock.

    Linux portability (factoria-linux-bus 2026-05-22): no-op on non-Darwin.
    Linux has no equivalent system Dock managed by `defaults`.
    """
    if platform.system() != "Darwin":
        return True  # nothing to remove; treat as success for uninstall flow
    try:
        subprocess.run(["bash", "-c", """
python3 -c "
import subprocess, plistlib
dock = subprocess.run(['defaults', 'export', 'com.apple.dock', '-'], capture_output=True)
pl = plistlib.loads(dock.stdout)
before = len(pl.get('persistent-apps', []))
pl['persistent-apps'] = [a for a in pl.get('persistent-apps', [])
    if 'Nexe' not in str(a.get('tile-data', {}).get('file-label', ''))]
if len(pl['persistent-apps']) < before:
    out = plistlib.dumps(pl)
    subprocess.run(['defaults', 'import', 'com.apple.dock', '-'], input=out)
    subprocess.run(['killall', 'Dock'])
"
"""], capture_output=True, timeout=15)  # nosec B603 B607: literal heredoc bash script with no external interpolation; bash via PATH (Dock cleanup, macOS-only)
        return True
    except Exception:
        return False


def remove_login_items() -> bool:
    """Remove Nexe from macOS Login Items / Linux autostart.

    Linux portability (factoria-linux-bus 2026-05-22): on Linux removes
    ``~/.config/autostart/nexe-app.desktop`` (written by
    ``install_headless._register_linux_autostart``).
    """
    if platform.system() == "Linux":
        try:
            desktop_file = Path.home() / ".config" / "autostart" / "nexe-app.desktop"
            if desktop_file.exists():
                desktop_file.unlink()
            return True
        except Exception:
            return False
    if platform.system() != "Darwin":
        return True  # no-op on other platforms
    try:
        subprocess.run([  # nosec B603 B607: literal osascript command targeting our own Login Item; osascript via PATH (macOS-only)
            "osascript", "-e",
            'tell application "System Events" to delete login item "Nexe"'
        ], capture_output=True, timeout=10)
        return True
    except Exception:
        return False


NS_STATUS_WINDOW_LEVEL = 25  # above any normal app window


class _ForegroundContext:
    """Context manager that promotes the tray to .regular for an entire alert
    flow and returns it to .accessory (menubar only) on exit. Done ONCE to
    avoid interfering with the modal event loop between alerts (the cause of
    alerts being 'skipped' — activation policy flip-flop).
    """
    def __init__(self):
        self.old_policy = None

    def __enter__(self):
        try:
            from AppKit import NSApp, NSApplicationActivationPolicyRegular
            self.old_policy = NSApp.activationPolicy()
            NSApp.setActivationPolicy_(NSApplicationActivationPolicyRegular)
            NSApp.activateIgnoringOtherApps_(True)
        except Exception:  # nosec B110: best-effort AppKit activation policy promotion; non-fatal if AppKit unavailable
            pass
        return self

    def __exit__(self, *exc):
        if self.old_policy is not None:
            try:
                from AppKit import NSApp
                NSApp.setActivationPolicy_(self.old_policy)
            except Exception:  # nosec B110: best-effort AppKit activation policy restore on context exit; non-fatal
                pass


def _front_alert_rumps_fallback(title, message, ok, cancel, other):
    """Fallback path when AppKit is unavailable: delegate to rumps.alert."""
    import rumps
    kwargs = {}
    if title is not None:
        kwargs["title"] = title
    if message is not None:
        kwargs["message"] = message
    if ok is not None:
        kwargs["ok"] = ok
    if cancel is not None:
        kwargs["cancel"] = cancel
    if other is not None:
        kwargs["other"] = other
    return rumps.alert(**kwargs)


def _build_nsalert(title, message, ok, cancel, other):
    """Construct and configure an NSAlert with buttons."""
    from AppKit import NSAlert, NSAlertStyleWarning
    alert = NSAlert.alloc().init()
    if title is not None:
        alert.setMessageText_(str(title))
    if message is not None:
        alert.setInformativeText_(str(message))
    alert.setAlertStyle_(NSAlertStyleWarning)
    alert.addButtonWithTitle_(str(ok) if ok is not None else "OK")
    if cancel is not None:
        alert.addButtonWithTitle_(str(cancel))
    if other is not None:
        alert.addButtonWithTitle_(str(other))
    return alert


def _nsalert_response_to_int(response):
    """Convert NSAlertFirstButtonReturn=1000, Second=1001, Third=1002 to ints."""
    if response == 1000:
        return 1
    elif response == 1001:
        return 0
    elif response == 1002:
        return -1
    return response


def _front_alert(title=None, message=None, ok=None, cancel=None, other=None, **_):
    """Show an always-on-top NSAlert.

    Assumes activation policy is ALREADY promoted to .regular (via
    _ForegroundContext in the caller). Only raises window level and calls
    runModal. Return compat with rumps: 1 (OK) / 0 (Cancel) / -1 (Other).
    """
    try:
        alert = _build_nsalert(title, message, ok, cancel, other)
    except Exception:
        return _front_alert_rumps_fallback(title, message, ok, cancel, other)

    window = alert.window()
    window.setLevel_(NS_STATUS_WINDOW_LEVEL)
    window.makeKeyAndOrderFront_(None)

    return _nsalert_response_to_int(alert.runModal())


def _uninstall_confirm_dialogs(install_dir: Path, t_func) -> tuple:
    """Show the 3 confirmation dialogs. Return (cancelled, keep_data, storage_dir)."""
    storage_text = t_func("uninstall_storage", size=calculate_storage(install_dir))
    with _ForegroundContext():
        response = _front_alert(
            title=t_func("uninstall_title"),
            message=t_func("uninstall_warning", storage=storage_text, path=str(install_dir)),
            ok="No",
            cancel=t_func("uninstall_title"),
        )
        if response != 0:
            return True, False, None

        response2 = _front_alert(
            title=t_func("uninstall_title"),
            message=t_func("uninstall_confirm"),
            ok="No",
            cancel=t_func("uninstall_title"),
        )
        if response2 != 0:
            return True, False, None

        keep_data = False
        storage_dir = install_dir / "storage"
        if storage_dir.exists():
            data_response = _front_alert(
                title=t_func("uninstall_data_title"),
                message=t_func("uninstall_data_message"),
                ok=t_func("uninstall_keep_data"),
                cancel=t_func("uninstall_delete_all"),
            )
            keep_data = (data_response == 1)
    return False, keep_data, storage_dir


def _uninstall_backup_storage(storage_dir: Path, keep_data: bool, t_func, removed, failed):
    """Optionally backup storage/ and report outcome into removed/failed."""
    backup_path = None
    if keep_data and storage_dir is not None and storage_dir.exists():
        from datetime import datetime
        backup_name = f"nexe-backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        backup_path = Path.home() / backup_name
        try:
            shutil.copytree(storage_dir, backup_path)
        except Exception:
            backup_path = None
    if keep_data:
        if backup_path:
            removed.append(t_func("uninstall_backup_ok", path=str(backup_path)))
        else:
            failed.append(t_func("uninstall_backup_failed"))


def _uninstall_remove_system_entries(removed, failed):
    """Remove Login Items, Dock entry, /usr/local/bin/nexe and /Applications/Nexe.app."""
    if remove_login_items():
        removed.append("Login Items")
    else:
        failed.append("Login Items")

    if remove_from_dock():
        removed.append("Dock")
    else:
        failed.append("Dock")

    nexe_symlink = Path("/usr/local/bin/nexe")
    if nexe_symlink.is_symlink() or nexe_symlink.exists():
        try:
            nexe_symlink.unlink()
            removed.append("/usr/local/bin/nexe")
        except PermissionError:
            failed.append("/usr/local/bin/nexe (permission denied)")
        except Exception:
            failed.append("/usr/local/bin/nexe")

    # macOS-only: /Applications/Nexe.app legacy bundle removal.
    # Linux portability (factoria-linux-bus 2026-05-22): skip on non-Darwin
    # (no /Applications layout on Linux).
    if platform.system() == "Darwin":
        nexe_app = Path("/Applications/Nexe.app")
        if nexe_app.exists():
            try:
                shutil.rmtree(nexe_app)
                removed.append("/Applications/Nexe.app")
            except Exception:
                failed.append("/Applications/Nexe.app")

    # User-data support dir cleanup. Resolved via platformdirs so the path
    # matches whatever install_headless._write_project_marker wrote:
    #   - macOS:   ~/Library/Application Support/Nexe
    #   - Linux:   $XDG_DATA_HOME or ~/.local/share/Nexe
    try:
        import platformdirs
        support_dir = Path(platformdirs.user_data_dir("Nexe"))
    except ImportError:
        # Fallback to historical mac path so an uninstall on a corrupted env
        # still cleans something. Linux without platformdirs ends up a no-op.
        support_dir = Path.home() / "Library" / "Application Support" / "Nexe"
    if support_dir.exists():
        try:
            shutil.rmtree(support_dir)
            removed.append(str(support_dir))
        except Exception:
            failed.append(str(support_dir))


def _uninstall_remove_install_dir(install_dir: Path, removed, failed):
    """Schedule removal of install_dir via a detached shell script."""
    cleanup_script = f"""#!/bin/bash
sleep 2
rm -rf "{install_dir}" && touch /tmp/nexe_uninstall_ok || touch /tmp/nexe_uninstall_failed
"""
    try:
        subprocess.Popen(  # nosec B603 B607: install_dir is resolved Path derived from PROJECT_ROOT (controlled by tray app); mono-user can rm directly; bash via PATH
            ["bash", "-c", cleanup_script],
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        removed.append(str(install_dir))
    except Exception:
        failed.append(str(install_dir))


def perform_uninstall(install_dir: Path, t_func, stop_server_func) -> tuple:
    """
    Perform the full uninstall process.

    Args:
        install_dir: Path to the Nexe installation directory
        t_func: Translation function (key, **kwargs) -> str
        stop_server_func: Callable to stop the running server

    Returns:
        (removed: list[str], failed: list[str])
    """
    cancelled, keep_data, storage_dir = _uninstall_confirm_dialogs(install_dir, t_func)
    if cancelled:
        return None, None

    removed: list[str] = []
    failed: list[str] = []

    _uninstall_backup_storage(storage_dir, keep_data, t_func, removed, failed)
    stop_server_func()
    _uninstall_remove_system_entries(removed, failed)
    _uninstall_remove_install_dir(install_dir, removed, failed)

    return removed, failed
