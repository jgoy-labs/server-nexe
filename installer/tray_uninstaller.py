"""
────────────────────────────────────
Server Nexe
Location: installer/tray_uninstaller.py
Description: Uninstall logic for the tray app.
────────────────────────────────────
"""

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
    """Remove Nexe.app from the macOS Dock."""
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
"""], capture_output=True, timeout=15)
        return True
    except Exception:
        return False


def remove_login_items() -> bool:
    """Remove Nexe from macOS Login Items."""
    try:
        subprocess.run([
            "osascript", "-e",
            'tell application "System Events" to delete login item "Nexe"'
        ], capture_output=True, timeout=10)
        return True
    except Exception:
        return False


def _front_alert(*args, **kwargs):
    """Show a rumps.alert, activating the app first so it appears on top."""
    import rumps
    try:
        from AppKit import NSApp
        NSApp.activateIgnoringOtherApps_(True)
    except Exception:
        pass
    return rumps.alert(*args, **kwargs)


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
    # Calculate storage before showing warning
    storage_text = t_func("uninstall_storage", size=calculate_storage(install_dir))

    # First window: warning with what will be deleted
    response = _front_alert(
        title=t_func("uninstall_title"),
        message=t_func("uninstall_warning", storage=storage_text),
        ok="No",
        cancel=t_func("uninstall_title"),
    )
    if response != 0:
        return None, None  # User cancelled

    # Second window: final confirmation
    response2 = _front_alert(
        title=t_func("uninstall_title"),
        message=t_func("uninstall_confirm"),
        ok="No",
        cancel=t_func("uninstall_title"),
    )
    if response2 != 0:
        return None, None  # User cancelled

    # Third window: ask about data backup
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

    # Backup storage/ if requested
    backup_path = None
    if keep_data and storage_dir.exists():
        from datetime import datetime
        backup_name = f"nexe-backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        backup_path = Path.home() / backup_name
        try:
            shutil.copytree(storage_dir, backup_path)
        except Exception:
            backup_path = None

    # Stop server
    stop_server_func()

    removed = []
    failed = []

    # Report backup result
    if keep_data:
        if backup_path:
            removed.append(t_func("uninstall_backup_ok", path=str(backup_path)))
        else:
            failed.append(t_func("uninstall_backup_failed"))

    # Remove from Login Items
    if remove_login_items():
        removed.append("Login Items")
    else:
        failed.append("Login Items")

    # Remove from Dock
    if remove_from_dock():
        removed.append("Dock")
    else:
        failed.append("Dock")

    # Remove /usr/local/bin/nexe symlink
    nexe_symlink = Path("/usr/local/bin/nexe")
    if nexe_symlink.is_symlink() or nexe_symlink.exists():
        try:
            nexe_symlink.unlink()
            removed.append("/usr/local/bin/nexe")
        except PermissionError:
            failed.append("/usr/local/bin/nexe (permis denegat)")
        except Exception:
            failed.append("/usr/local/bin/nexe")

    # Remove /Applications/Nexe.app
    nexe_app = Path("/Applications/Nexe.app")
    if nexe_app.exists():
        try:
            shutil.rmtree(nexe_app)
            removed.append("/Applications/Nexe.app")
        except Exception:
            failed.append("/Applications/Nexe.app")

    # Remove installation directory using a detached shell script
    cleanup_script = f"""#!/bin/bash
sleep 2
rm -rf "{install_dir}" && touch /tmp/nexe_uninstall_ok || touch /tmp/nexe_uninstall_failed
"""
    try:
        subprocess.Popen(
            ["bash", "-c", cleanup_script],
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        removed.append(str(install_dir))
    except Exception:
        failed.append(str(install_dir))

    return removed, failed
