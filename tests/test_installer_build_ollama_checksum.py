"""
────────────────────────────────────
Server Nexe
Location: tests/test_installer_build_ollama_checksum.py
Description: Smoke tests for the SHA256 pinning of the Ollama bundle download
             added in B8 r4 (build-time MITM hardening for the DMG).

             Covers:
               - installer/ollama-checksums.txt exists with a valid 64-char hex
                 SHA256 and the expected filename.
               - shasum -a 256 -c correctly REJECTS a corrupt local zip in a
                 sandbox (no network download, no 156 MB transfer).
               - installer/build-ollama-bundle.sh actually invokes
                 `shasum -a 256 -c "$CHECKSUMS_FILE"` and contains the `exit 4`
                 branch on mismatch — i.e. the verification is wired in, not
                 declared and silently skipped.
               - The script contains none of the well-known silencing patterns
                 that would defeat the check (|| true, set +e, NEXE_SKIP_CHECKSUM,
                 2>/dev/null applied to the shasum invocation).

             These are auditor-grade adversarial checks, not just smoke. The
             cost of catching a regression here is far smaller than the cost
             of shipping a Trojanized Ollama binary inside the DMG.

             B8 r4 / Auditoria r4.
────────────────────────────────────
"""

from __future__ import annotations

import hashlib
import os
import re
import secrets
import subprocess
from pathlib import Path

_ROOT = Path(__file__).parent.parent
_SCRIPT = _ROOT / "installer" / "build-ollama-bundle.sh"
_CHECKSUMS = _ROOT / "installer" / "ollama-checksums.txt"

_SHA256_HEX_RE = re.compile(r"^[a-f0-9]{64}$")


def _read_pin() -> tuple[str, str]:
    """Return (sha256_hex, filename) of the active (non-comment) line."""
    lines = [
        ln.strip()
        for ln in _CHECKSUMS.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.lstrip().startswith("#")
    ]
    assert len(lines) == 1, (
        f"Expected exactly one active checksum line, got {len(lines)}: {lines!r}"
    )
    parts = lines[0].split()
    assert len(parts) == 2, f"Malformed line (need '<sha256>  <filename>'): {lines[0]!r}"
    return parts[0], parts[1]


# ═══════════════════════════════════════════════════════════════════════
# 1. Pin file format
# ═══════════════════════════════════════════════════════════════════════


def test_ollama_checksums_file_has_valid_sha256_pin() -> None:
    """The pin file must exist and contain a 64-char hex SHA for Ollama-darwin.zip."""
    assert _CHECKSUMS.exists(), f"Checksums file missing: {_CHECKSUMS}"

    sha_hex, filename = _read_pin()

    assert _SHA256_HEX_RE.match(sha_hex), (
        f"SHA256 pin is not 64 lowercase hex chars: {sha_hex!r}"
    )
    assert filename == "Ollama-darwin.zip", (
        f"Pin filename must be 'Ollama-darwin.zip' (relative), got {filename!r}"
    )


# ═══════════════════════════════════════════════════════════════════════
# 2. Adversarial — shasum -c rejects a corrupt local file
# ═══════════════════════════════════════════════════════════════════════


def test_shasum_check_rejects_corrupt_zip(tmp_path: Path) -> None:
    """Drop a random-bytes file at <tmp>/Ollama-darwin.zip and confirm `shasum -c`
    fails. Probability of a random 4 KB blob matching the pinned SHA is ~2^-256
    — effectively zero. No network download involved."""
    fake_zip = tmp_path / "Ollama-darwin.zip"
    fake_zip.write_bytes(secrets.token_bytes(4096))

    # Belt-and-braces: confirm we are not testing against an accidental match.
    pinned_sha, _ = _read_pin()
    actual_sha = hashlib.sha256(fake_zip.read_bytes()).hexdigest()
    assert actual_sha != pinned_sha, (
        "Test setup invalid: random bytes happen to match the pinned SHA "
        "(astronomically unlikely — investigate the RNG)."
    )

    # `shasum -c` must exit non-zero (it returns 1 on mismatch).
    result = subprocess.run(
        ["shasum", "-a", "256", "-c", str(_CHECKSUMS), "--status"],
        cwd=tmp_path,
        check=False,
        capture_output=True,
    )
    assert result.returncode != 0, (
        "shasum -c accepted a corrupt zip — the integrity check is broken!"
    )


# ═══════════════════════════════════════════════════════════════════════
# 3. The build script actually wires shasum -c in (no theatre)
# ═══════════════════════════════════════════════════════════════════════


def test_build_script_invokes_shasum_check() -> None:
    """The verification must be a real call to `shasum -a 256 -c`, not a
    decorative comment, and it must abort with `exit 4` on mismatch."""
    assert _SCRIPT.exists(), f"Build script missing: {_SCRIPT}"
    text = _SCRIPT.read_text(encoding="utf-8")

    # Strip comments so we only inspect executable code.
    code_only = "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )

    assert "shasum -a 256 -c" in code_only, (
        "Build script does not invoke `shasum -a 256 -c` outside of comments — "
        "the SHA256 verification is missing or has been disabled."
    )
    assert "exit 4" in code_only, (
        "Build script does not contain the `exit 4` branch — a SHA256 mismatch "
        "would not abort the build."
    )
    assert "ollama-checksums.txt" in code_only, (
        "Build script does not reference the checksums file in executable code."
    )


# ═══════════════════════════════════════════════════════════════════════
# 4. No silencing patterns sneaking past the check
# ═══════════════════════════════════════════════════════════════════════


def test_build_script_has_no_shasum_silencing_patterns() -> None:
    """A well-meaning future change ("just make CI green") could quietly
    neutralise the check. Forbid the well-known shapes."""
    text = _SCRIPT.read_text(encoding="utf-8")

    # `set +e` anywhere disables the abort-on-error guarantee.
    assert "set +e" not in text, (
        "`set +e` would disable abort-on-error and let a failed shasum slip through."
    )

    # `NEXE_SKIP_CHECKSUM` env var or any opt-out flag for the check.
    assert "NEXE_SKIP_CHECKSUM" not in text, (
        "An env-var bypass for the SHA256 check is not allowed."
    )

    # `shasum ... || true` or `shasum ... || :` — silently swallows mismatch.
    silencing_re = re.compile(r"shasum[^\n]*\|\|\s*(true|:)\b")
    assert not silencing_re.search(text), (
        "`shasum ... || true` (or `|| :`) silences mismatch — forbidden."
    )

    # `shasum ... 2>/dev/null` would hide the diagnostic on failure.
    shasum_to_devnull_re = re.compile(r"shasum[^\n]*2>\s*/dev/null")
    assert not shasum_to_devnull_re.search(text), (
        "Redirecting shasum's stderr to /dev/null hides mismatch diagnostics."
    )


# ═══════════════════════════════════════════════════════════════════════
# 5. Bash syntax (sanity)
# ═══════════════════════════════════════════════════════════════════════


def test_build_script_bash_syntax_clean() -> None:
    result = subprocess.run(
        ["bash", "-n", str(_SCRIPT)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"bash -n failed:\n{result.stderr}"


def test_build_script_is_executable() -> None:
    assert os.access(_SCRIPT, os.X_OK), f"Script not executable: {_SCRIPT}"
