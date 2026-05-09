"""
────────────────────────────────────
Server Nexe
Location: installer/installer_reinstall.py
Description: Helpers for managing existing installations with 3 modes:
             - wipe      → deletes user data (.env, storage/, venv); preserves knowledge/ (system)
             - overwrite → overwrites code/binaries/catalog, preserving user data
             - backup    → backs up data to <root>/.nexe-backups/<timestamp>/ then wipes

Bug 7 fix — previously reinstallation cleaned nothing, so the same
NEXE_PRIMARY_API_KEY persisted, Qdrant memory was not cleared, and the
knowledge base was duplicated by re-ingestion.

Important notes (Consultant advisories):

1. Before applying any mode, the server (supervisor) is stopped if
   running. If not stopped, Qdrant and other processes may be writing
   during the backup/wipe → corruption.

2. `overwrite` mode regenerates `.env` via `_update_env_model_config()`
   keeping NEXE_PRIMARY_API_KEY and NEXE_CSRF_SECRET but refreshing
   the model configuration (because the wizard allows changing the model
   on reinstall). Without regenerating this would leave inconsistencies.

3. `overwrite` mode deletes `storage/.knowledge_ingested` so the next
   startup re-indexes and the KB is not left with stale chunks.

4. Backup uses `shutil.move` (instant on the same volume) instead of
   `copytree` (slow and 2x disk). By default excludes `storage/models/`
   (which can be 30+ GB). Opt-in via `exclude_models=False`.

5. Wipe refuses to run if project_root matches the bundle of the current
   process (`Install Nexe.app/Contents/Resources/...`). Otherwise we
   shoot ourselves in the foot by deleting the executable that is
   running us.

6. The master encryption key lives in the macOS Keychain (service
   `server-nexe`, user `master-encryption-key`) with fallback to
   `~/.nexe/master.key`. By default `wipe` does NOT touch the Keychain
   entry. Opt-in via `wipe_keychain=True`.

7. OAuth files `~/.nexe/mail365_tokens.json` and `~/.nexe/mail365.json`
   are outside project_root and no mode touches them by default. Opt-in
   via `wipe_home_nexe=True` to delete them explicitly.
────────────────────────────────────
"""

from __future__ import annotations

import logging
import os
import shutil
import signal
import subprocess  # nosec B404: subprocess required to pgrep stale nexe-tray before venv replacement (B10 fix); usage validated below
import sys
import time
from pathlib import Path
from typing import Callable, Iterable, List, Optional

logger = logging.getLogger(__name__)

# Valid modes — exposed as strings for use in CLI/GUI
REINSTALL_MODE_WIPE = "wipe"
REINSTALL_MODE_OVERWRITE = "overwrite"
REINSTALL_MODE_BACKUP = "backup"
VALID_REINSTALL_MODES = (
    REINSTALL_MODE_WIPE,
    REINSTALL_MODE_OVERWRITE,
    REINSTALL_MODE_BACKUP,
)
DEFAULT_REINSTALL_MODE = REINSTALL_MODE_BACKUP

# Existing installation markers (any one indicates a prior installation)
INSTALL_MARKERS = (".env", "storage", "venv")

# Paths considered "user data" — backup/wipe touches them
# knowledge/ is NOT user data — it is system documentation that comes from the payload.
# Wipe + reinstall overwrites knowledge/ automatically via tar.
USER_DATA_PATHS = (".env", "storage")

# Paths considered "system" — overwrite may also touch them
SYSTEM_PATHS = ("venv", "qdrant", "nexe", "core", "memory", "personality", "plugins", "knowledge")

# Keychain identifiers — must match core/crypto/keys.py
KEYRING_SERVICE = "server-nexe"
KEYRING_USERNAME = "master-encryption-key"

# Persistent OAuth files at ~/.nexe/ (not inside project_root)
HOME_NEXE_FILES = ("mail365_tokens.json", "mail365.json")


# ── Stop server helpers ─────────────────────────────────────────────────


def _read_pid_file(pid_file: Path) -> Optional[int]:
    """Read and return the PID from pid_file, or None if corrupt/missing.

    Deletes a corrupt pid_file and logs a warning.
    """
    try:
        return int(pid_file.read_text().strip())
    except (OSError, ValueError) as e:
        logger.warning("Could not read supervisor PID file: %s", e)
        try:
            pid_file.unlink()
        except OSError:
            pass
        return None


def _check_pid_alive(pid: int) -> Optional[bool]:
    """Return True if pid exists, False if dead, None if permission denied."""
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return None


def _wait_for_pid_exit(pid: int, pid_file: Path, timeout: float) -> bool:
    """Poll until pid exits or timeout. Clean up pid_file on exit. Return True if gone."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            try:
                pid_file.unlink()
            except OSError:
                pass
            return True
        time.sleep(0.2)
    return False


def _sigkill_pid(pid: int, pid_file: Path) -> bool:
    """Send SIGKILL to pid and confirm it is dead. Return True if gone."""
    logger.warning("Supervisor PID=%d did not exit on SIGTERM, sending SIGKILL", pid)
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except PermissionError:
        return False

    time.sleep(0.5)
    alive = _check_pid_alive(pid)
    if alive:
        return False  # still alive
    try:
        pid_file.unlink()
    except OSError:
        pass
    return True


def _default_stop_server(project_root: Path, timeout: float = 10.0) -> bool:
    """Stop the supervisor if it is running via PID file at storage/logs/.

    Returns True if a process was stopped or if there was none. Returns
    False if there was a process but it could not be stopped.
    """
    pid_file = project_root / "storage" / "logs" / "core_supervisor.pid"
    if not pid_file.exists():
        return True

    pid = _read_pid_file(pid_file)
    if pid is None:
        return True  # Corrupt pid file was cleaned up

    alive = _check_pid_alive(pid)
    if alive is False:
        try:
            pid_file.unlink()
        except OSError:
            pass
        return True
    if alive is None:
        logger.warning("No permission to signal supervisor PID %d", pid)
        return False

    # Send SIGTERM and wait
    logger.info("Stopping running supervisor PID=%d before reinstall", pid)
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False

    if _wait_for_pid_exit(pid, pid_file, timeout):
        return True

    return _sigkill_pid(pid, pid_file)


def detect_existing_install(project_root: Path) -> bool:
    """Return True if project_root contains a prior installation."""
    return any((project_root / m).exists() for m in INSTALL_MARKERS)


def _is_project_root_running_bundle(project_root: Path) -> bool:
    """True if the current process lives inside project_root (self-destruction).

    If the installer runs from `Install Nexe.app/Contents/...` and
    project_root points at the same bundle, doing a wipe would shoot us
    in the foot by deleting our own executable/libs.
    """
    try:
        project_resolved = project_root.resolve()
    except (OSError, RuntimeError):
        return False

    # Note: do NOT use Path(__file__) — in headless mode, installer scripts
    # are loaded via PYTHONPATH from project_root, so __file__ resolves
    # inside project_root. That is correct and does not mean the binary
    # lives there. We only check sys.executable (the actual process binary,
    # which in the DMG wizard lives inside the DMG bundle).
    candidates: list[Path] = []
    try:
        exe = Path(sys.executable).resolve()
        candidates.append(exe)
    except (OSError, RuntimeError):
        pass

    for c in candidates:
        try:
            if c == project_resolved or project_resolved in c.parents:
                return True
        except (OSError, ValueError):
            continue
    return False


def _safe_remove(path: Path) -> None:
    """Delete file or directory if it exists. Does not fail if absent."""
    if not path.exists() and not path.is_symlink():
        return
    if path.is_symlink() or path.is_file():
        try:
            path.unlink()
        except FileNotFoundError:
            pass
    elif path.is_dir():
        shutil.rmtree(path, ignore_errors=False)


def _wipe_keychain_master_key() -> bool:
    """Delete the master key entry from the keyring. Best-effort."""
    try:
        import keyring
        keyring.delete_password(KEYRING_SERVICE, KEYRING_USERNAME)
        logger.info("Master key removed from keyring")
        return True
    except Exception as e:
        logger.debug("Keyring delete failed or entry not present: %s", e)
        return False


def _wipe_home_nexe_oauth() -> List[Path]:
    """Delete OAuth tokens at ~/.nexe/mail365*.json. Opt-in."""
    removed: List[Path] = []
    home_nexe = Path.home() / ".nexe"
    for name in HOME_NEXE_FILES:
        p = home_nexe / name
        if p.exists() or p.is_symlink():
            try:
                p.unlink()
                removed.append(p)
            except OSError as e:
                logger.warning("Could not remove %s: %s", p, e)
    return removed


def wipe_user_data(
    project_root: Path,
    paths: Iterable[str] = USER_DATA_PATHS,
    wipe_keychain: bool = False,
    wipe_home_nexe: bool = False,
) -> List[Path]:
    """Mode 'wipe': delete user data (.env, storage/, knowledge/).

    By default does NOT touch:
    - macOS Keychain (service `server-nexe`, user `master-encryption-key`)
    - ~/.nexe/mail365_tokens.json, ~/.nexe/mail365.json (OAuth tokens)

    Args:
        project_root: root of the server-nexe project.
        paths: paths relative to project_root to delete.
        wipe_keychain: if True, delete the master key entry from the keyring.
        wipe_home_nexe: if True, delete ~/.nexe/mail365*.json.

    Returns the list of paths that were actually deleted.
    """
    removed: List[Path] = []
    for rel in paths:
        target = project_root / rel
        if target.exists() or target.is_symlink():
            _safe_remove(target)
            removed.append(target)

    if wipe_keychain:
        if _wipe_keychain_master_key():
            removed.append(Path(f"keyring://{KEYRING_SERVICE}/{KEYRING_USERNAME}"))

    if wipe_home_nexe:
        removed.extend(_wipe_home_nexe_oauth())

    return removed


def backup_user_data(
    project_root: Path,
    backup_root: Path | None = None,
    paths: Iterable[str] = USER_DATA_PATHS,
    exclude_models: bool = True,
) -> Path:
    """Mode 'backup': move user data to backup_root/<timestamp>/.

    Uses `shutil.move` (instant on the same volume) instead of
    `copytree` (slow and requires 2x disk). This is critical because
    `storage/models/` can be 30+ GB.

    By default excludes `storage/models/` from the backup
    (`exclude_models=True`). Models are large and in a typical reinstall
    the user re-downloads them (or keeps them opt-in).

    By default backup_root is `project_root/.nexe-backups`, outside
    `storage/` — this ensures the subsequent wipe does NOT delete the
    backup we just made. Returns the path of the created backup.
    """
    if backup_root is None:
        backup_root = project_root / ".nexe-backups"
    backup_root.mkdir(parents=True, exist_ok=True)

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    backup_dir = backup_root / timestamp
    suffix = 0
    while backup_dir.exists():
        suffix += 1
        backup_dir = backup_root / f"{timestamp}_{suffix}"
    backup_dir.mkdir(parents=True)

    backup_root_resolved = backup_root.resolve()

    for rel in paths:
        src = project_root / rel
        if not src.exists():
            continue
        dest = backup_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)

        # Special case: if it is 'storage' and we want to exclude models
        # or avoid recursion inside the backup_root itself, handle it separately.
        needs_special_storage = False
        if src.is_dir():
            try:
                src_resolved = src.resolve()
                if backup_root_resolved == src_resolved or backup_root_resolved.is_relative_to(src_resolved):
                    needs_special_storage = True
            except (OSError, ValueError):
                pass
            if exclude_models and rel == "storage" and (src / "models").exists():
                needs_special_storage = True

        if needs_special_storage:
            # Move child entries one by one, skipping 'models/' and '.nexe-backups'
            # if they live inside. Remaining subdirectories are moved intact.
            dest.mkdir(parents=True, exist_ok=True)
            for child in src.iterdir():
                if exclude_models and child.name == "models":
                    continue
                try:
                    child_resolved = child.resolve()
                    if backup_root_resolved == child_resolved or backup_root_resolved.is_relative_to(child_resolved):
                        continue
                except (OSError, ValueError):
                    pass
                shutil.move(str(child), str(dest / child.name))
            # After moving valid children, if 'src' still has things
            # inside (models or the backup_root itself), leave it in place.
            # Otherwise delete it so the subsequent wipe has nothing to do.
            try:
                remaining = list(src.iterdir())
                if not remaining:
                    src.rmdir()
            except OSError:
                pass
            continue

        # General case: direct move (instant on the same volume)
        shutil.move(str(src), str(dest))

    return backup_dir


def _regenerate_env_for_overwrite(project_root: Path) -> bool:
    """Mark `.env` for model-config regeneration while preserving secrets.

    In `overwrite` mode, the new wizard code will call `generate_env_file`
    which in turn calls `_update_env_model_config` if `.env` already exists.
    That function preserves NEXE_PRIMARY_API_KEY and NEXE_CSRF_SECRET
    (unmatched lines go through the merge `else`) but refreshes the model
    configuration.

    Nothing is done here: we only validate that the file exists and is
    readable. The actual regeneration happens when `install.py` /
    `install_headless.py` calls `generate_env_file(project_root, model_config)`
    later.

    Returns True if `.env` exists and is valid for the subsequent merge.
    """
    env_file = project_root / ".env"
    if not env_file.exists():
        return False
    try:
        _ = env_file.read_text()
        return True
    except OSError as e:
        logger.warning("Could not read .env for overwrite merge: %s", e)
        return False


def _kill_existing_tray() -> None:
    """Kill the existing nexe-tray process before replacing the venv (B10)."""
    result = subprocess.run(["pgrep", "-f", "nexe-tray"], capture_output=True, text=True)  # nosec B603 B607: literal pgrep pattern; system tool via PATH (mono-user local)
    for pid_str in result.stdout.strip().splitlines():
        try:
            os.kill(int(pid_str), signal.SIGTERM)
        except (ProcessLookupError, ValueError):
            pass


def apply_reinstall_mode(
    project_root: Path,
    mode: str,
    backup_root: Path | None = None,
    stop_server_func: Optional[Callable[[Path], bool]] = None,
    exclude_models: bool = True,
    wipe_keychain: bool = False,
    wipe_home_nexe: bool = False,
) -> dict:
    """Apply the chosen mode and return a summary of what was done.

    Args:
        project_root: root of the server-nexe project.
        mode: one of VALID_REINSTALL_MODES.
        backup_root: optional — backup destination (backup mode only).
        stop_server_func: optional — callable(project_root) -> bool to
            stop the server before touching anything. Defaults to
            `_default_stop_server` which checks the pidfile at
            storage/logs/core_supervisor.pid.
        exclude_models: backup mode — exclude storage/models/.
        wipe_keychain: wipe mode — delete master key from keyring.
        wipe_home_nexe: wipe mode — delete ~/.nexe/mail365*.json.

    Returns:
        dict with keys: mode, removed (List[str]), backup_dir (str|None),
        server_stopped (bool).
    """
    if mode not in VALID_REINSTALL_MODES:
        raise ValueError(
            f"Invalid reinstall mode: {mode!r}. "
            f"Valid modes: {', '.join(VALID_REINSTALL_MODES)}"
        )

    # Advisory 5 — refuse if project_root is the bundle where the process lives.
    # Only applies if the mode will touch things inside project_root.
    if mode in (REINSTALL_MODE_WIPE, REINSTALL_MODE_BACKUP):
        if _is_project_root_running_bundle(project_root):
            raise RuntimeError(
                f"Refusing to wipe project_root={project_root!r}: "
                "the running installer process lives inside this path. "
                "Install to a different location (e.g. ~/nexe) or run "
                "the installer from outside the bundle."
            )

    # Advisory 1 — stop the server before any mode
    if stop_server_func is None:
        stop_server_func = _default_stop_server
    server_stopped = False
    try:
        server_stopped = bool(stop_server_func(project_root))
    except Exception as e:
        logger.warning("stop_server_func raised: %s", e)
        server_stopped = False
    if not server_stopped:
        raise RuntimeError(
            "Could not stop the running Nexe server before reinstall. "
            "Stop it manually and retry."
        )

    result: dict = {
        "mode": mode,
        "removed": [],
        "backup_dir": None,
        "server_stopped": server_stopped,
    }

    if mode == REINSTALL_MODE_OVERWRITE:
        # Advisory 2 — validate that .env will be regenerable via merge.
        # Actual regeneration is done by generate_env_file() later in the
        # installer flow; here we only check integrity.
        _regenerate_env_for_overwrite(project_root)

        # Advisory 3 — delete KB ingestion marker so the new code
        # re-indexes and no stale chunks remain.
        marker = project_root / "storage" / ".knowledge_ingested"
        if marker.exists():
            try:
                marker.unlink()
                result["removed"].append(str(marker))
            except OSError as e:
                logger.warning("Could not remove knowledge marker: %s", e)

        # Kill existing tray before replacing the venv
        _kill_existing_tray()
        # Remove the venv (will be regenerated). Keep .env, storage/, knowledge/.
        venv = project_root / "venv"
        if venv.exists():
            _safe_remove(venv)
            result["removed"].append(str(venv))
        return result

    if mode == REINSTALL_MODE_BACKUP:
        backup_dir = backup_user_data(
            project_root,
            backup_root=backup_root,
            exclude_models=exclude_models,
        )
        result["backup_dir"] = str(backup_dir)

        # Dev #3 fix — Bug 7 Consultant pass 1:
        # Previously we called wipe_user_data with the default paths
        # (.env, storage, knowledge). Since `storage/` was handled via
        # shutil.rmtree, models preserved with exclude_models=True were
        # deleted anyway. Solution (b): when exclude_models=True, do a
        # selective wipe of storage/ removing everything EXCEPT models/.
        # The other paths (.env, knowledge/) have already been moved by
        # backup_user_data; we still pass them to wipe in case anything
        # residual remains.
        if exclude_models:
            wipe_paths = [".env"]  # knowledge/ NO: it's system code, tar will refill it
            removed = wipe_user_data(
                project_root,
                paths=wipe_paths,
                wipe_keychain=wipe_keychain,
                wipe_home_nexe=wipe_home_nexe,
            )
            # Wipe selectiu de storage/: tot excepte models/
            storage_dir = project_root / "storage"
            if storage_dir.exists() and storage_dir.is_dir():
                for child in storage_dir.iterdir():
                    if child.name == "models":
                        continue
                    _safe_remove(child)
                    removed.append(child)
        else:
            # Without model preservation, normal full wipe.
            removed = wipe_user_data(
                project_root,
                wipe_keychain=wipe_keychain,
                wipe_home_nexe=wipe_home_nexe,
            )

        result["removed"] = [str(p) for p in removed]
        # Kill existing tray before replacing the venv
        _kill_existing_tray()
        venv = project_root / "venv"
        if venv.exists():
            _safe_remove(venv)
            result["removed"].append(str(venv))
        return result

    # mode == REINSTALL_MODE_WIPE
    removed = wipe_user_data(
        project_root,
        wipe_keychain=wipe_keychain,
        wipe_home_nexe=wipe_home_nexe,
    )
    result["removed"] = [str(p) for p in removed]
    # Kill existing tray before replacing the venv
    _kill_existing_tray()
    venv = project_root / "venv"
    if venv.exists():
        _safe_remove(venv)
        result["removed"].append(str(venv))
    return result


__all__ = [
    "REINSTALL_MODE_WIPE",
    "REINSTALL_MODE_OVERWRITE",
    "REINSTALL_MODE_BACKUP",
    "VALID_REINSTALL_MODES",
    "DEFAULT_REINSTALL_MODE",
    "detect_existing_install",
    "wipe_user_data",
    "backup_user_data",
    "apply_reinstall_mode",
]
