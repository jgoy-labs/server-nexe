"""
────────────────────────────────────
Server Nexe
Location: installer/installer_ollama_install.py
Description: Installation of the Ollama runtime (app/binary) on macOS and
             Linux, plus the helpers that locate an existing binary or a
             bundled offline zip inside the DMG.

This module was split out of ``installer_setup_models.py`` on 2026-04-23
to keep the parent under the 500-line rule SHA256
verification code landed. The model-download functions stay in the old
file; anything that concerns *bringing Ollama to the system* lives here.
────────────────────────────────────
"""

from __future__ import annotations

import os
import platform
import subprocess
import time
import shutil
import zipfile
from pathlib import Path

from .installer_display import (
    BOLD, CYAN, DIM, RESET,
    print_step, print_success, print_warn,
)
from .installer_i18n import t


def _safe_extract_zip(zf: zipfile.ZipFile, dest_dir: str) -> None:
    """Extract a ZipFile to ``dest_dir`` rejecting any
    member that escapes the destination (Zip Slip).

    Validates each ``ZipInfo.filename`` by resolving it against ``dest_dir``
    and ensuring the resulting absolute path stays inside ``dest_dir`` after
    realpath normalisation. Absolute paths and ``..`` segments are refused.

    Raises ``RuntimeError`` on the first offending member, leaving partially
    extracted files behind (caller is expected to clean up the destination
    on failure — same contract as ``zipfile.extractall``).
    """
    real_dest = os.path.realpath(dest_dir)
    for member in zf.infolist():
        # Reject absolute paths and unsafe characters early.
        if member.filename.startswith(('/', '\\')):
            raise RuntimeError(
                f"Zip Slip refused: absolute path entry {member.filename!r}"
            )
        target = os.path.realpath(os.path.join(real_dest, member.filename))
        # The resolved path must live inside dest_dir; using os.path.commonpath
        # rather than startswith avoids the classic /foo vs /foobar mismatch.
        try:
            common = os.path.commonpath([real_dest, target])
        except ValueError:
            # Different drives on Windows, mismatched anchors, etc.
            raise RuntimeError(
                f"Zip Slip refused: path resolution failed for {member.filename!r}"
            )
        if common != real_dest:
            raise RuntimeError(
                f"Zip Slip refused: {member.filename!r} would escape to {target!r}"
            )
    zf.extractall(real_dest)


_OLLAMA_PIN_ENV = {
    "darwin": "NEXE_OLLAMA_MACOS_SHA256",
    "linux_install_sh": "NEXE_OLLAMA_INSTALL_SHA256",
    "windows_arm64": "NEXE_OLLAMA_WINDOWS_SHA256",
    "windows_amd64": "NEXE_OLLAMA_WINDOWS_SHA256",
}


def _resolve_ollama_pin(key: str) -> tuple[str | None, str | None, str | None]:
    """WS9-01: resolve (expected_sha256, pinned_url, pinned_version).

    Resolution order:
      1. operator env override (NEXE_OLLAMA_*_SHA256) — keeps the default
         download URL (the operator pinned whatever that URL serves);
      2. embedded release pin from installer/provider_pins.json section
         ``ollama_installer`` — carries a VERSIONED GitHub URL (and the
         Ollama version), so an upstream release cannot drift under the pin;
      3. (None, None, None) — no pin available (corrupt/missing pins file);
         the caller must fail closed unless NEXE_ALLOW_UNPINNED consents.
    """
    env_pin = os.environ.get(_OLLAMA_PIN_ENV[key], "").strip().lower()
    if env_pin:
        return env_pin, None, None
    try:
        import json
        pins_path = Path(__file__).with_name("provider_pins.json")
        section = json.loads(pins_path.read_text()).get("ollama_installer", {})
        entry = section.get(key) or {}
        sha = (entry.get("sha256") or "").strip().lower()
        if sha:
            return sha, entry.get("url") or None, section.get("version") or None
    except Exception:  # nosec — fall through to the fail-closed branch in the caller
        pass
    return None, None, None


def _unpinned_ollama_allowed(artefact: str) -> bool:
    """WS9-01: no pin at all → refuse to execute an unverified binary unless
    the operator explicitly opted in. Never a silent fail-open."""
    if os.environ.get("NEXE_ALLOW_UNPINNED", "").strip().lower() in {"1", "true", "yes"}:
        print_warn(
            f"No SHA-256 pin for {artefact} — proceeding UNPINNED "
            f"(NEXE_ALLOW_UNPINNED is set)."
        )
        return True
    print_warn(
        f"No SHA-256 pin available for {artefact} (neither env override nor "
        f"provider_pins.json). Refusing to execute an unverified binary — "
        f"set the NEXE_OLLAMA_*_SHA256 pin or NEXE_ALLOW_UNPINNED=1."
    )
    return False


def _find_ollama() -> str:
    """Locate the ollama binary — app bundles run with a minimal PATH."""
    found = shutil.which("ollama")
    if found:
        return found
    if platform.system().lower() == "windows":
        # Windows is never on PATH from a sidecar; check the standalone-zip
        # install location (and the default OllamaSetup.exe per-user target).
        candidates = [
            os.path.expanduser(r"~\AppData\Local\Programs\Ollama\ollama.exe"),
        ]
    else:
        candidates = [
            "/usr/local/bin/ollama",
            "/opt/homebrew/bin/ollama",  # nosemgrep
            os.path.expanduser("~/bin/ollama"),
            "/Applications/Ollama.app/Contents/Resources/ollama",
        ]
    for path in candidates:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return "ollama"  # fallback — let subprocess raise FileNotFoundError


def _find_bundle_ollama_zip():
    """Locate ``Ollama-darwin.zip`` inside the DMG bundle resources.

    Same lookup precedence as ``_find_bundle_resources()`` in
    ``installer_setup_env.py``:

    1. ``NEXE_BUNDLE_RESOURCES`` environment variable.
    2. Co-located ``InstallNexe.app`` in the repo root (development layout).
    3. Mounted DMG volumes under ``/Volumes/``.
    """
    candidates = []

    env_path = os.environ.get("NEXE_BUNDLE_RESOURCES")
    if env_path:
        candidates.append(Path(env_path) / "ollama" / "Ollama-darwin.zip")

    project_root = Path(__file__).parent.parent
    candidates.append(
        project_root / "InstallNexe.app" / "Contents" / "Resources"
        / "ollama" / "Ollama-darwin.zip"
    )

    volumes = Path("/Volumes")
    if volumes.is_dir():
        try:
            for vol in volumes.iterdir():
                candidates.append(
                    vol / "InstallNexe.app" / "Contents" / "Resources"
                    / "ollama" / "Ollama-darwin.zip"
                )
        except PermissionError:
            pass

    for c in candidates:
        if c.is_file():
            return c
    return None


def ensure_ollama_installed(headless: bool = False) -> bool:
    """Install Ollama if it isn't on the host already.

    In ``headless=True`` mode (CLI / Swift wizard) the interactive
    confirmation is skipped because the user already chose a model that
    requires Ollama. On macOS we extract ``Ollama.app`` into
    ``/Applications/`` and launch it (first launch registers the CLI at
    ``/usr/local/bin/ollama``); on Linux we pipe the official install
    script.
    """
    ollama_bin = _find_ollama()
    if os.path.isfile(ollama_bin):
        print_success(t('ollama_installed'))
        return True

    print_step(f"{BOLD}{t('installing_ollama')}{RESET}")

    if not headless:
        confirm = input(f"{t('ollama_install_confirm')} {t('yes_no')}: ").lower()
        if confirm == 'n':
            print_warn(t('ollama_install_skipped'))
            print(f"  {DIM}{t('ollama_install_manual')}{RESET}")
            return False

    system = platform.system().lower()
    if system == "darwin":
        return _install_ollama_macos()
    if system == "linux":
        return _install_ollama_linux()
    if system == "windows":
        return _install_ollama_windows()
    print_warn(f"Ollama auto-install not supported on {system}")
    print(f"  {DIM}{t('ollama_install_manual')}{RESET}")
    return False


def _install_ollama_macos() -> bool:
    """Install ``Ollama.app`` on macOS, preferring the DMG bundle when present.

    Lookup order:
      1. Bundled zip at ``InstallNexe.app/Contents/Resources/ollama/Ollama-darwin.zip``
         (placed there by ``build-ollama-bundle.sh``; the DMG install is
         then 100 % offline).
      2. Online download from ``ollama.com/download/Ollama-darwin.zip``.

    When downloading online, the SHA-256 digest is compared against
    ``NEXE_OLLAMA_MACOS_SHA256`` (env var) if set; a mismatch aborts the
    install.  This mirrors the Linux path which already verified against
    ``NEXE_OLLAMA_INSTALL_SHA256``.

    Post-extract we strip quarantine so Gatekeeper does not block the
    launch, open the app (which registers the CLI on first run), and poll
    for the binary to appear at ``/usr/local/bin/ollama``.
    """
    import hashlib
    import tempfile

    url = "https://ollama.com/download/Ollama-darwin.zip"
    dest = Path("/Applications/Ollama.app")
    # WS9-01: env override → embedded versioned pin → fail closed.
    expected_sha256, _pinned_url, _ = _resolve_ollama_pin("darwin")
    if _pinned_url:
        url = _pinned_url

    try:
        bundle_zip = _find_bundle_ollama_zip()
        if bundle_zip:
            print("  📦 Ollama offline: installing from bundle...")
            zip_path = str(bundle_zip)
        else:
            print("  📥 Downloading Ollama for macOS...")
            tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
            zip_path = tmp.name
            tmp.close()
            result = subprocess.run(  # nosec B603 B607: url is literal "https://ollama.com/download/Ollama-darwin.zip"; zip_path is tempfile mktemp; curl via PATH
                ["curl", "-fSL", "-o", zip_path, url],
                timeout=300, capture_output=True,
            )
            if result.returncode != 0:
                print_warn(t('ollama_install_failed'))
                print(f"  {CYAN}Download: {url}{RESET}")
                return False

            with open(zip_path, "rb") as _f:
                observed_sha256 = hashlib.sha256(_f.read()).hexdigest()
            print(f"  {DIM}Ollama-darwin.zip SHA-256: {observed_sha256}{RESET}")

            if expected_sha256:
                if observed_sha256 != expected_sha256:
                    print_warn(
                        f"Ollama-darwin.zip SHA-256 mismatch: "
                        f"expected {expected_sha256}, got {observed_sha256}. Aborting install."
                    )
                    os.unlink(zip_path)
                    return False
                print(f"  {DIM}SHA-256 matches the Ollama installer pin{RESET}")
            elif not _unpinned_ollama_allowed("Ollama-darwin.zip"):
                os.unlink(zip_path)
                return False

        print("  📦 Installing to /Applications/Ollama.app...")
        # Zip Slip protection. zipfile.extractall
        # follows arbitrary paths inside the archive (including absolute paths
        # and ../traversals), so a tampered Ollama-darwin.zip could write
        # anywhere on disk under the current user's privileges. The helper
        # below resolves each member against the target dir and refuses any
        # entry whose normalised path escapes it.
        with zipfile.ZipFile(zip_path, 'r') as zf:
            _safe_extract_zip(zf, "/Applications/")

        if not bundle_zip and os.path.isfile(zip_path):
            os.unlink(zip_path)

        subprocess.run(  # nosec B603 B607: dest is hardcoded /Applications/Ollama.app Path; xattr via PATH
            ["xattr", "-rd", "com.apple.quarantine", str(dest)],
            capture_output=True,
        )

        print("  🚀 Starting Ollama...")
        subprocess.run(["open", "-a", "Ollama"], capture_output=True)  # nosec B603 B607: literal `open -a Ollama`; macOS open via PATH

        for _ in range(15):
            time.sleep(2)
            ollama_bin = _find_ollama()
            if os.path.isfile(ollama_bin):
                print_success(t('ollama_installed'))
                return True

        print_warn("Ollama.app installed but CLI not yet available — try again in a moment")
        return True

    except subprocess.TimeoutExpired:
        print_warn("Ollama download timed out (>5 min)")
        return False
    except Exception as e:
        print_warn(f"{t('ollama_install_failed')}: {e}")
        print(f"  {CYAN}{url}{RESET}")
        return False


def _install_ollama_linux() -> bool:
    """Install Ollama on Linux via the official install script.

    Instead of piping `curl | bash` (which executes whatever bytes the
    network returns), download the script to a tempfile first and verify
    its SHA-256 against the pin (WS9-01: env override → embedded versioned
    pin from provider_pins.json → fail closed unless NEXE_ALLOW_UNPINNED).
    With the embedded pin the script comes from the VERSIONED raw URL and
    OLLAMA_VERSION pins the binary the script installs.
    """
    import hashlib
    import os
    import tempfile

    url = "https://ollama.com/install.sh"
    expected, _pinned_url, _pinned_version = _resolve_ollama_pin("linux_install_sh")
    if _pinned_url:
        url = _pinned_url
    tmp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix="ollama-install-", suffix=".sh", delete=False
        ) as f:
            tmp_path = f.name

        print(f"  {DIM}curl -fsSL {url} -o {tmp_path}{RESET}")
        dl = subprocess.run(  # nosec B603 B607: literal upstream URL; output is a local tempfile; curl via PATH
            ["curl", "-fsSL", url, "-o", tmp_path],
            timeout=60,
        )
        if dl.returncode != 0:
            print_warn(t('ollama_install_failed'))
            return False

        with open(tmp_path, "rb") as f:
            observed = hashlib.sha256(f.read()).hexdigest()
        print(f"  {DIM}install.sh SHA-256: {observed}{RESET}")

        if expected:
            if observed != expected:
                print_warn(
                    f"Ollama install.sh SHA-256 mismatch: "
                    f"expected {expected}, got {observed}. Aborting install."
                )
                return False
            print(f"  {DIM}SHA-256 matches the Ollama installer pin{RESET}")
        elif not _unpinned_ollama_allowed("ollama install.sh"):
            return False

        script_env = dict(os.environ)
        if _pinned_version:
            # Pin the BINARY the script installs, not just the script bytes.
            script_env["OLLAMA_VERSION"] = _pinned_version.lstrip("v")
        result = subprocess.run(  # nosec B603 B607: tmp_path is a tempfile we just created and hashed; bash via PATH
            ["bash", tmp_path],
            timeout=180,
            env=script_env,
        )
        if result.returncode == 0:
            print_success(t('ollama_installed'))
            return True
        print_warn(t('ollama_install_failed'))
        return False
    except subprocess.TimeoutExpired:
        print_warn("Ollama install timed out (>3 min)")
        return False
    except Exception as e:
        print_warn(f"{t('ollama_install_failed')}: {e}")
        print(f"  {CYAN}curl -fsSL {url} -o /tmp/install.sh && bash /tmp/install.sh{RESET}")
        return False
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def _install_ollama_windows() -> bool:
    """Install Ollama on Windows from the official standalone zip.

    Windows ships no ``Ollama.app`` and the GUI installer (``OllamaSetup.exe``)
    is an InnoSetup wizard whose silent mode is broken upstream
    (ollama/ollama#7969), so we mirror the macOS zip-extraction path instead:
    download ``ollama-windows-<arch>.zip`` and unpack it (Zip-Slip-guarded)
    under ``%LOCALAPPDATA%\\Programs\\Ollama`` — the same location _find_ollama
    and OLLAMA_BIN_CANDIDATES look in. Unlike macOS there is no tray app, so we
    also start ``ollama serve`` headless and wait for the daemon to accept
    connections, otherwise the ``ollama pull`` that follows cannot connect.

    The SHA-256 is compared against ``NEXE_OLLAMA_WINDOWS_SHA256`` when set
    (opt-in pin, like the macOS/Linux paths); a mismatch aborts the install.
    """
    import hashlib
    import socket
    import tempfile

    # Lazy import: this module is also loaded by the standalone macOS DMG path
    # where `core` may not be on sys.path at import time; here (Windows sidecar
    # onboarding) core is always importable.
    from core.proc_utils import no_window_kwargs

    arch = "arm64" if platform.machine().lower() in ("arm64", "aarch64") else "amd64"
    url = f"https://ollama.com/download/ollama-windows-{arch}.zip"
    dest = Path(os.path.expandvars(r"%LOCALAPPDATA%\Programs\Ollama"))
    # WS9-01: env override → embedded versioned pin → fail closed.
    expected_sha256, _pinned_url, _ = _resolve_ollama_pin(f"windows_{arch}")
    if _pinned_url:
        url = _pinned_url
    zip_path: str | None = None
    # CREATE_NEW_PROCESS_GROUP (0x200) | CREATE_NO_WINDOW (0x0800_0000): serve runs
    # in its own group with NO console window. We do NOT use DETACHED_PROCESS (0x8):
    # per MSDN it makes Windows IGNORE CREATE_NO_WINDOW, so `ollama serve` would pop
    # a VISIBLE console — the "terminals flashing" bug the 06/07 fix missed.
    detached_no_window = 0x0000_0200 | 0x0800_0000

    try:
        # No emoji: the Windows sidecar stdout is cp1252, not UTF-8 — a raw
        # print() of an emoji raises UnicodeEncodeError and aborts the install.
        print("  Downloading Ollama for Windows...")
        tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
        zip_path = tmp.name
        tmp.close()
        result = subprocess.run(  # nosec B603 B607: url is the literal ollama.com download; zip_path is our tempfile; curl ships with Windows 10+
            ["curl", "-fSL", "-o", zip_path, url],
            timeout=600, capture_output=True,
            # Windows: CREATE_NO_WINDOW — the forgotten sibling of the serve at
            # ~line 420; without it curl flashes a console window on download.
            **no_window_kwargs(),
        )
        if result.returncode != 0:
            print_warn(t('ollama_install_failed'))
            print(f"  {CYAN}Download: {url}{RESET}")
            return False

        with open(zip_path, "rb") as _f:
            observed_sha256 = hashlib.sha256(_f.read()).hexdigest()
        print(f"  {DIM}ollama-windows-{arch}.zip SHA-256: {observed_sha256}{RESET}")
        if expected_sha256:
            if observed_sha256 != expected_sha256:
                print_warn(
                    f"ollama-windows-{arch}.zip SHA-256 mismatch: "
                    f"expected {expected_sha256}, got {observed_sha256}. Aborting install."
                )
                return False
            print(f"  {DIM}SHA-256 matches the Ollama installer pin{RESET}")
        elif not _unpinned_ollama_allowed(f"ollama-windows-{arch}.zip"):
            return False

        dest.mkdir(parents=True, exist_ok=True)
        print(f"  Installing to {dest}...")
        # Zip Slip protection (same helper as macOS): a tampered archive must
        # not write outside dest via absolute paths or ../ traversals.
        with zipfile.ZipFile(zip_path, 'r') as zf:
            _safe_extract_zip(zf, str(dest))

        ollama_exe = dest / "ollama.exe"
        if not ollama_exe.is_file():
            print_warn("Ollama zip extracted but ollama.exe not found")
            return False

        print("  Starting Ollama...")
        try:
            subprocess.Popen(  # nosec B603: ollama_exe is the file we just extracted under our own %LOCALAPPDATA%; literal `serve`
                [str(ollama_exe), "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=detached_no_window,
            )
        except Exception as e:  # noqa: BLE001 — serve is best-effort; the pull will surface a clear error if it never came up
            print_warn(f"ollama serve did not start: {e}")

        # Wait for the daemon to accept connections so the subsequent
        # `ollama pull` can reach it (default 127.0.0.1:11434).
        for _ in range(20):
            try:
                with socket.create_connection(("127.0.0.1", 11434), timeout=1):
                    print_success(t('ollama_installed'))
                    return True
            except OSError:
                time.sleep(1)
        # Binary is installed even if serve is slow; let the pull retry.
        print_success(t('ollama_installed'))
        return True

    except subprocess.TimeoutExpired:
        print_warn("Ollama download timed out (>10 min)")
        return False
    except Exception as e:
        print_warn(f"{t('ollama_install_failed')}: {e}")
        print(f"  {CYAN}{url}{RESET}")
        return False
    finally:
        if zip_path and os.path.isfile(zip_path):
            try:
                os.unlink(zip_path)
            except OSError:
                pass


__all__ = [
    "_find_ollama",
    "_find_bundle_ollama_zip",
    "ensure_ollama_installed",
    "_install_ollama_macos",
    "_install_ollama_linux",
    "_install_ollama_windows",
]
