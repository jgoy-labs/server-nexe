"""
────────────────────────────────────
Server Nexe
Location: installer/installer_reinstall.py
Description: Helpers per gestionar instal·lacions existents amb 3 modes:
             - wipe      → esborra tot (.env, storage/, knowledge/, venv, qdrant)
             - overwrite → sobreescriu codi/binaris/catàleg, preservant dades d'usuari
             - backup    → fa backup de dades a <root>/.nexe-backups/<timestamp>/ i després wipe

Bug 7 fix — abans la reinstal·lació no netejava res, així que la mateixa
NEXE_PRIMARY_API_KEY persistia, la memòria Qdrant no es netejava i la
knowledge base es duplicava per re-ingestió.

Notes importants (avisos Consultor):

1. Abans d'aplicar qualsevol mode es para el servidor (supervisor) si
   està corrent. Si no el parem, Qdrant i altres processos poden estar
   escrivint durant el backup/wipe → corrupció.

2. Mode `overwrite` regenera `.env` via `_update_env_model_config()`
   mantenint NEXE_PRIMARY_API_KEY i NEXE_CSRF_SECRET però refrescant
   la configuració de model (perquè el wizard permet canviar de model
   al reinstal·lar). Si no es regenerés quedaria incoherència.

3. Mode `overwrite` esborra `storage/.knowledge_ingested` perquè el
   proper startup torni a indexar i la KB no quedi amb chunks vells.

4. Backup usa `shutil.move` (instantani al mateix volum) en comptes de
   `copytree` (lent i 2x disc). Per defecte exclou `storage/models/`
   (que pot ser 30+ GB). Opt-in via `exclude_models=False`.

5. Wipe refusa executar-se si el project_root coincideix amb el bundle
   del procés actual (`Install Nexe.app/Contents/Resources/...`). Sinó
   ens disparem al peu esborrant l'executable que ens està corrent.

6. La master encryption key viu al macOS Keychain (servei `server-nexe`,
   user `master-encryption-key`) amb fallback a `~/.nexe/master.key`.
   Per defecte `wipe` NO toca la Keychain entry. Opt-in via
   `wipe_keychain=True`.

7. Fitxers OAuth `~/.nexe/mail365_tokens.json` i `~/.nexe/mail365.json`
   són fora del project_root i cap mode els toca per defecte. Opt-in
   via `wipe_home_nexe=True` per esborrar-los explícitament.
────────────────────────────────────
"""

from __future__ import annotations

import logging
import os
import shutil
import signal
import sys
import time
from pathlib import Path
from typing import Callable, Iterable, List, Optional

logger = logging.getLogger(__name__)

# Modes vàlids — exposats com a string per ús al CLI/GUI
REINSTALL_MODE_WIPE = "wipe"
REINSTALL_MODE_OVERWRITE = "overwrite"
REINSTALL_MODE_BACKUP = "backup"
VALID_REINSTALL_MODES = (
    REINSTALL_MODE_WIPE,
    REINSTALL_MODE_OVERWRITE,
    REINSTALL_MODE_BACKUP,
)
DEFAULT_REINSTALL_MODE = REINSTALL_MODE_BACKUP

# Marcadors d'instal·lació existent (qualsevol indica instal·lació prèvia)
INSTALL_MARKERS = (".env", "storage", "venv", "knowledge")

# Paths considerats "dades d'usuari" — backup/wipe els toca
USER_DATA_PATHS = (".env", "storage", "knowledge")

# Paths considerats "sistema" — overwrite també els pot tocar
SYSTEM_PATHS = ("venv", "qdrant", "nexe", "core", "memory", "personality", "plugins")

# Keychain identifiers — han de coincidir amb core/crypto/keys.py
KEYRING_SERVICE = "server-nexe"
KEYRING_USERNAME = "master-encryption-key"

# Fitxers OAuth persistents a ~/.nexe/ (no dins project_root)
HOME_NEXE_FILES = ("mail365_tokens.json", "mail365.json")


# ── Stop server helpers ─────────────────────────────────────────────────


def _default_stop_server(project_root: Path, timeout: float = 10.0) -> bool:
    """Para el supervisor si està corrent via PID file a storage/logs/.

    Retorna True si s'ha parat un procés o si no n'hi havia. Retorna
    False si hi havia un procés però no s'ha pogut parar.
    """
    pid_file = project_root / "storage" / "logs" / "core_supervisor.pid"
    if not pid_file.exists():
        return True

    try:
        pid_str = pid_file.read_text().strip()
        pid = int(pid_str)
    except (OSError, ValueError) as e:
        logger.warning("Could not read supervisor PID file: %s", e)
        # PID file corrupte → esborrem-lo, considerem que no hi ha servidor
        try:
            pid_file.unlink()
        except OSError:
            pass
        return True

    # Comprova si el procés existeix
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        # Procés mort, només neteja el pidfile
        try:
            pid_file.unlink()
        except OSError:
            pass
        return True
    except PermissionError:
        logger.warning("No permission to signal supervisor PID %d", pid)
        return False

    # Envia SIGTERM i espera
    logger.info("Stopping running supervisor PID=%d before reinstall", pid)
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False

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

    # No ha mort → SIGKILL
    logger.warning("Supervisor PID=%d did not exit on SIGTERM, sending SIGKILL", pid)
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except PermissionError:
        return False

    # Darrera comprovació
    time.sleep(0.5)
    try:
        os.kill(pid, 0)
        return False  # encara viu
    except ProcessLookupError:
        try:
            pid_file.unlink()
        except OSError:
            pass
        return True


def detect_existing_install(project_root: Path) -> bool:
    """Retorna True si project_root conté una instal·lació prèvia."""
    return any((project_root / m).exists() for m in INSTALL_MARKERS)


def _is_project_root_running_bundle(project_root: Path) -> bool:
    """True si el procés actual viu dins project_root (auto-destrucció).

    Si l'instal·lador corre des de `Install Nexe.app/Contents/...` i
    project_root apunta al mateix bundle, fer wipe ens dispararia al peu
    esborrant el nostre propi executable/libs.
    """
    try:
        project_resolved = project_root.resolve()
    except (OSError, RuntimeError):
        return False

    candidates: list[Path] = []
    try:
        candidates.append(Path(__file__).resolve())
    except (OSError, RuntimeError):
        pass
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
    """Esborra fitxer o directori si existeix. No falla si no hi és."""
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
    """Esborra l'entrada de la master key del keyring. Best-effort."""
    try:
        import keyring
        keyring.delete_password(KEYRING_SERVICE, KEYRING_USERNAME)
        logger.info("Master key removed from keyring")
        return True
    except Exception as e:
        logger.debug("Keyring delete failed or entry not present: %s", e)
        return False


def _wipe_home_nexe_oauth() -> List[Path]:
    """Esborra tokens OAuth a ~/.nexe/mail365*.json. Opt-in."""
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
    """Mode 'wipe': esborra dades d'usuari (.env, storage/, knowledge/).

    Per defecte NO toca:
    - macOS Keychain (servei `server-nexe`, user `master-encryption-key`)
    - ~/.nexe/mail365_tokens.json, ~/.nexe/mail365.json (OAuth tokens)

    Args:
        project_root: arrel del projecte server-nexe.
        paths: paths relatius a project_root a esborrar.
        wipe_keychain: si True, esborra l'entrada de la master key del keyring.
        wipe_home_nexe: si True, esborra ~/.nexe/mail365*.json.

    Retorna la llista de paths que s'han esborrat efectivament.
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
    """Mode 'backup': mou dades d'usuari a backup_root/<timestamp>/.

    Usa `shutil.move` (instantani al mateix volum) en comptes de
    `copytree` (lent i requereix 2x disc). Això és crític perquè
    `storage/models/` pot ser 30+ GB.

    Per defecte exclou `storage/models/` del backup (paràmetre
    `exclude_models=True`). Els models són pesats i en una reinstal·lació
    típica l'usuari els re-descarrega (o els conserva opt-in).

    Per defecte backup_root és `project_root/.nexe-backups`, fora de
    `storage/` — això permet que el wipe posterior NO esborri el backup
    que acabem de fer. Retorna el path del backup creat.
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

        # Cas especial: si és 'storage' i volem excloure models o
        # evitar recursió dins del propi backup_root, ho tractem apart.
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
            # Mou entrades fill una per una, saltant 'models/' i '.nexe-backups'
            # si viuen dins. Les subcarpetes restants es mouen intactes.
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
            # Després de moure els fills vàlids, si 'src' encara té
            # coses dins (models o el propi backup_root), el deixem
            # al seu lloc. Altrament l'esborrem perquè el wipe posterior
            # no tingui feina.
            try:
                remaining = list(src.iterdir())
                if not remaining:
                    src.rmdir()
            except OSError:
                pass
            continue

        # Cas general: move directe (instantani al mateix volum)
        shutil.move(str(src), str(dest))

    return backup_dir


def _regenerate_env_for_overwrite(project_root: Path) -> bool:
    """Marca el `.env` per regenerar model config preservant secrets.

    En mode `overwrite`, el codi nou del wizard cridarà `generate_env_file`
    que al seu torn crida `_update_env_model_config` si el `.env` ja
    existeix. Aquesta funció preserva NEXE_PRIMARY_API_KEY i
    NEXE_CSRF_SECRET (linies sense match van pel `else` del merge) però
    refresca la config de model.

    Aquí no fem res: només validem que el fitxer existeix i és llegible.
    La regeneració real passa quan `install.py` / `install_headless.py`
    criden `generate_env_file(project_root, model_config)` més tard.

    Retorna True si el `.env` existeix i és vàlid per al merge posterior.
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


def apply_reinstall_mode(
    project_root: Path,
    mode: str,
    backup_root: Path | None = None,
    stop_server_func: Optional[Callable[[Path], bool]] = None,
    exclude_models: bool = True,
    wipe_keychain: bool = False,
    wipe_home_nexe: bool = False,
) -> dict:
    """Aplica el mode escollit i retorna un resum del que s'ha fet.

    Args:
        project_root: arrel del projecte server-nexe.
        mode: un de VALID_REINSTALL_MODES.
        backup_root: opcional — destí dels backups (només mode 'backup').
        stop_server_func: opcional — callable(project_root) -> bool per
            parar el servidor abans de tocar res. Per defecte s'usa
            `_default_stop_server` que mira el pidfile a
            storage/logs/core_supervisor.pid.
        exclude_models: mode backup — excloure storage/models/.
        wipe_keychain: mode wipe — esborrar master key del keyring.
        wipe_home_nexe: mode wipe — esborrar ~/.nexe/mail365*.json.

    Returns:
        dict amb claus: mode, removed (List[str]), backup_dir (str|None),
        server_stopped (bool).
    """
    if mode not in VALID_REINSTALL_MODES:
        raise ValueError(
            f"Invalid reinstall mode: {mode!r}. "
            f"Valid modes: {', '.join(VALID_REINSTALL_MODES)}"
        )

    # Aviso 5 — refusa si project_root és el bundle on viu el procés.
    # Només aplica si el mode tocarà coses dins del project_root.
    if mode in (REINSTALL_MODE_WIPE, REINSTALL_MODE_BACKUP):
        if _is_project_root_running_bundle(project_root):
            raise RuntimeError(
                f"Refusing to wipe project_root={project_root!r}: "
                "the running installer process lives inside this path. "
                "Install to a different location (e.g. ~/nexe) or run "
                "the installer from outside the bundle."
            )

    # Aviso 1 — parar el servidor abans de qualsevol mode
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
        # Aviso 2 — validar que .env serà regenerable via merge.
        # La regeneració real la fa generate_env_file() més tard al
        # flow de l'installer; aquí només comprovem integritat.
        _regenerate_env_for_overwrite(project_root)

        # Aviso 3 — esborrar marker de KB ingerida perquè el codi nou
        # torni a indexar i no quedin chunks vells.
        marker = project_root / "storage" / ".knowledge_ingested"
        if marker.exists():
            try:
                marker.unlink()
                result["removed"].append(str(marker))
            except OSError as e:
                logger.warning("Could not remove knowledge marker: %s", e)

        # Treiem el venv (es regenerarà). Mantenim .env, storage/, knowledge/.
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

        # Dev #3 fix — Bug 7 Consultor passada 1:
        # Abans aquí cridàvem wipe_user_data amb els paths per defecte
        # (.env, storage, knowledge). Com que `storage/` es feia via
        # shutil.rmtree, els models que havíem preservat amb
        # exclude_models=True s'esborraven igualment. Solució (b):
        # quan exclude_models=True, fem un wipe selectiu de storage/
        # eliminant tot el contingut EXCEPTE models/. La resta de
        # paths (.env, knowledge/) ja els ha mogut el backup_user_data,
        # els passem igualment al wipe per si alguna cosa residual.
        if exclude_models:
            wipe_paths = [".env", "knowledge"]
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
            # Sense preservació de models, wipe complet normal.
            removed = wipe_user_data(
                project_root,
                wipe_keychain=wipe_keychain,
                wipe_home_nexe=wipe_home_nexe,
            )

        result["removed"] = [str(p) for p in removed]
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
