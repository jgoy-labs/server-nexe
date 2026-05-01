"""
────────────────────────────────────
Server Nexe
Location: tests/test_installer_wheels_checksum.py
Description: Adversarial smoke tests for the SHA256 pinning of the Python
             wheels bundle added in v1.0.4-beta TODO 1.3 (build-time MITM
             hardening for the wheels shipped inside the DMG, B8 pattern —
             same threat model as the Ollama bundle pin in r4).

             Covers:
               - installer/wheels-checksums.txt exists with exactly 2 active
                 entries (torch + torchvision), each with a 64-char hex SHA
                 and the expected pinned filename pattern.
               - A sandbox with random-bytes files at the pinned filenames
                 makes `shasum -a 256 -c` correctly REJECT the bundle, with
                 no network download involved. This is the in-CI replacement
                 for the live-bundle tamper test (see test below for why a
                 byte-flip on the live $WHEELS_DIR is not viable: the build
                 script wipes $WHEELS_DIR at every run).
               - installer/build-wheels-bundle.sh wires the verification in
                 (it calls _sha256, references wheels-checksums.txt, and the
                 exit 7 / exit 8 abort branches are present in executable
                 code, not just in comments).
               - The build script contains none of the well-known silencing
                 patterns that would defeat the check (|| true, set +e,
                 NEXE_SKIP_CHECKSUM, 2>/dev/null applied to the SHA helper).

             These are auditor-grade adversarial checks, not just smoke. The
             cost of catching a regression here is far smaller than the cost
             of shipping a Trojanized PyTorch wheel inside the DMG.

             v1.0.4-beta TODO 1.3 / B8 pattern (sprint Fase 1).
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
_SCRIPT = _ROOT / "installer" / "build-wheels-bundle.sh"
_CHECKSUMS = _ROOT / "installer" / "wheels-checksums.txt"

_SHA256_HEX_RE = re.compile(r"^[a-f0-9]{64}$")
_TORCH_PIN_RE = re.compile(
    r"^torch-\d+\.\d+\.\d+-cp312-cp312-macosx_\d+_\d+_arm64\.whl$"
)
_TORCHVISION_PIN_RE = re.compile(
    r"^torchvision-\d+\.\d+\.\d+-cp312-cp312-macosx_\d+_\d+_arm64\.whl$"
)


def _read_active_pins() -> list[tuple[str, str]]:
    """Return [(sha256_hex, filename), ...] for every non-comment, non-empty line."""
    pins: list[tuple[str, str]] = []
    for raw in _CHECKSUMS.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        assert len(parts) == 2, (
            f"Malformed line (need '<sha256>  <filename>'): {raw!r}"
        )
        pins.append((parts[0], parts[1]))
    return pins


# ═══════════════════════════════════════════════════════════════════════
# 1. Pin file format
# ═══════════════════════════════════════════════════════════════════════


def test_wheels_checksums_file_exists() -> None:
    assert _CHECKSUMS.exists(), f"Checksums file missing: {_CHECKSUMS}"


def test_wheels_checksums_has_exactly_torch_and_torchvision() -> None:
    """Exactly 2 active entries: one torch, one torchvision. Adding a 3rd
    pinned wheel without updating this test is a code review signal."""
    pins = _read_active_pins()
    assert len(pins) == 2, (
        f"Expected exactly 2 active checksum lines (torch + torchvision), "
        f"got {len(pins)}: {pins!r}"
    )

    filenames = [name for _, name in pins]
    torch_pins = [n for n in filenames if n.startswith("torch-")]
    torchvision_pins = [n for n in filenames if n.startswith("torchvision-")]
    assert len(torch_pins) == 1, f"Expected 1 torch pin, got: {torch_pins!r}"
    assert len(torchvision_pins) == 1, (
        f"Expected 1 torchvision pin, got: {torchvision_pins!r}"
    )


def test_wheels_checksums_have_valid_sha256_hex() -> None:
    """Every pinned hash must be 64 lowercase hex chars."""
    for sha_hex, filename in _read_active_pins():
        assert _SHA256_HEX_RE.match(sha_hex), (
            f"SHA256 pin is not 64 lowercase hex chars: "
            f"{sha_hex!r} for {filename!r}"
        )


def test_wheels_checksums_filename_pattern() -> None:
    """Pinned filenames must match the cp312 macosx arm64 wheel pattern.
    Verified empirically 2026-05-01: PyPI publishes the wheels with min
    macOS version 11.0 on arm64. pip resolves them upward for macOS 14+
    hosts; pinning the literal filename means an unexpected upstream re-cut
    to a different platform tag would be caught as exit 7 (missing pinned
    wheel) at build time."""
    for sha_hex, filename in _read_active_pins():
        if filename.startswith("torch-"):
            assert _TORCH_PIN_RE.match(filename), (
                f"torch pin filename does not match expected pattern: {filename!r}"
            )
        elif filename.startswith("torchvision-"):
            assert _TORCHVISION_PIN_RE.match(filename), (
                f"torchvision pin filename does not match expected pattern: {filename!r}"
            )
        else:
            raise AssertionError(
                f"Unexpected pinned wheel (only torch/torchvision allowed): "
                f"{filename!r} (sha={sha_hex})"
            )


def test_wheels_checksums_separator_is_two_spaces() -> None:
    """Format must be `<sha>  <filename>` (two spaces) so the file remains
    `shasum -a 256 -c` compatible if a future maintainer prefers that over
    the manual loop in the build script."""
    for raw in _CHECKSUMS.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip("\n")
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        # Strict: exactly two spaces between sha and filename, no leading
        # whitespace, no trailing whitespace.
        assert re.match(r"^[a-f0-9]{64}  [^ ].*[^ ]$", line), (
            f"Active line is not in `<sha256>  <filename>` (two-space) format: "
            f"{line!r}"
        )


# ═══════════════════════════════════════════════════════════════════════
# 2. Adversarial — shasum -c rejects corrupt wheels at the pinned names
# ═══════════════════════════════════════════════════════════════════════


def test_shasum_check_rejects_corrupt_wheels(tmp_path: Path) -> None:
    """Drop random-bytes files at the pinned filenames in a sandbox and
    confirm `shasum -a 256 -c` rejects them. Probability of a random 4 KB
    blob matching either pinned SHA is ~2^-256 — effectively zero. No
    network download involved.

    This is the in-CI replacement for a "tamper test on the live wheels
    bundle". The build script begins with `rm -rf "$WHEELS_DIR"` and
    re-downloads, so any byte-flip on a live wheel is wiped on the next
    run — making a live-bundle tamper test non-viable. Rejection of a
    corrupt file at the pinned filename is the same adversarial check,
    reproducible without network and runnable in CI."""
    pins = _read_active_pins()
    assert len(pins) == 2  # guarded by previous test, but explicit here

    for sha_hex, filename in pins:
        fake_wheel = tmp_path / filename
        fake_wheel.write_bytes(secrets.token_bytes(4096))
        # Belt-and-braces: the random blob's SHA must NOT match the pin.
        actual_sha = hashlib.sha256(fake_wheel.read_bytes()).hexdigest()
        assert actual_sha != sha_hex, (
            f"Test setup invalid: random bytes match pinned SHA for "
            f"{filename!r} (astronomically unlikely — investigate the RNG)."
        )

    # `shasum -c` reads the file from CWD; run inside tmp_path so it
    # finds our random-bytes files at the pinned filenames.
    result = subprocess.run(
        ["shasum", "-a", "256", "-c", str(_CHECKSUMS), "--status"],
        cwd=tmp_path,
        check=False,
        capture_output=True,
    )
    assert result.returncode != 0, (
        "shasum -c accepted random-bytes files at the pinned filenames — "
        "the SHA256 verification format is broken!"
    )


# ═══════════════════════════════════════════════════════════════════════
# 3. The build script actually wires SHA verification in (no theatre)
# ═══════════════════════════════════════════════════════════════════════


def test_build_script_invokes_sha256_verification() -> None:
    """The verification must be a real call to a SHA helper that reads
    wheels-checksums.txt, with `exit 7` (missing wheel) and `exit 8`
    (mismatch) abort branches present in EXECUTABLE code, not in comments."""
    assert _SCRIPT.exists(), f"Build script missing: {_SCRIPT}"
    text = _SCRIPT.read_text(encoding="utf-8")

    # Strip comments so we only inspect executable code.
    code_only = "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )

    assert "_sha256" in code_only, (
        "Build script does not invoke the _sha256 helper outside of comments — "
        "the SHA256 verification helper is missing."
    )
    assert "wheels-checksums.txt" in code_only, (
        "Build script does not reference wheels-checksums.txt in executable code."
    )
    assert "exit 7" in code_only, (
        "Build script does not contain the `exit 7` branch — a pinned wheel "
        "missing from the bundle would not abort the build."
    )
    assert "exit 8" in code_only, (
        "Build script does not contain the `exit 8` branch — a SHA256 mismatch "
        "would not abort the build."
    )


def test_build_script_defines_sha256_helper() -> None:
    """The _sha256() helper must be defined in the script (copied from
    build-embedding-bundle.sh) and use sha256sum/shasum with no eval/exec."""
    text = _SCRIPT.read_text(encoding="utf-8")
    assert "_sha256()" in text, "_sha256() helper definition missing"
    assert "sha256sum" in text, "_sha256 must call sha256sum (GNU)"
    assert "shasum -a 256" in text, "_sha256 must fall back to shasum -a 256 (BSD)"
    # No dangerous primitives in the helper neighborhood.
    assert " eval " not in text and "$(eval" not in text, (
        "eval is not allowed in the SHA verification path"
    )


# ═══════════════════════════════════════════════════════════════════════
# 4. No silencing patterns sneaking past the check
# ═══════════════════════════════════════════════════════════════════════


def test_build_script_has_no_silencing_patterns() -> None:
    """A well-meaning future change ("just make CI green") could quietly
    neutralise the SHA check. Forbid the well-known shapes."""
    text = _SCRIPT.read_text(encoding="utf-8")

    # `set +e` anywhere disables the abort-on-error guarantee. The script
    # must rely solely on `set -euo pipefail` at the top.
    assert "set +e" not in text, (
        "`set +e` would disable abort-on-error and let a failed SHA check slip through."
    )

    # No env-var bypass for the check.
    assert "NEXE_SKIP_CHECKSUM" not in text, (
        "An env-var bypass for the SHA256 check is not allowed."
    )
    assert "SKIP_SHA" not in text and "NO_VERIFY" not in text, (
        "An env-var bypass for the SHA256 check is not allowed."
    )

    # `_sha256 ... || true` or `_sha256 ... || :` would silently swallow failure.
    silencing_re = re.compile(r"_sha256[^\n]*\|\|\s*(true|:)\b")
    assert not silencing_re.search(text), (
        "`_sha256 ... || true` (or `|| :`) silences errors — forbidden."
    )

    # `_sha256 ... 2>/dev/null` would hide the diagnostic on failure.
    sha_to_devnull_re = re.compile(r"_sha256[^\n]*2>\s*/dev/null")
    assert not sha_to_devnull_re.search(text), (
        "Redirecting _sha256's stderr to /dev/null hides mismatch diagnostics."
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


# ═══════════════════════════════════════════════════════════════════════
# 6. Adversarial — exercise the build script's REAL manual loop
# ═══════════════════════════════════════════════════════════════════════
# These tests cover the bypass paths flagged by the v1.0.4-beta TODO 1.3
# security review:
#   - missing checksums file → must abort (not WARN).
#   - empty / comments-only checksums file → must abort (zero verifications).
#   - trailing-newline-stripped file → last pin must still be verified.
#   - tampered wheel at the pinned filename → must abort with exit 8.
#   - path-traversal wheel name in checksums → must abort.
# Unlike the `shasum -c` test above, these run the actual code path in
# build-wheels-bundle.sh against a sandboxed $WHEELS_DIR + $CHECKSUMS_FILE,
# so a regression in the manual loop (wrong awk field, missing exit branch,
# silenced error) is caught here.

_STEP4B_BEGIN_RE = re.compile(
    r"^# ── Step 4b: SHA256 supply chain verification.*$", re.MULTILINE
)
_STEP4B_END_RE = re.compile(
    r"^# Expected critical wheels", re.MULTILINE
)


def _extract_step4b_block() -> str:
    """Pull the SHA verification block out of the build script as bash source.

    The block is bounded by the `Step 4b` header (start) and the `Expected
    critical wheels` header (start of Step 4 sanity-check tail). Extracting
    by markers means the test follows the script: if Step 4b is moved or
    rewritten, the markers move too and the test still exercises whatever
    code is actually run."""
    text = _SCRIPT.read_text(encoding="utf-8")
    start = _STEP4B_BEGIN_RE.search(text)
    end = _STEP4B_END_RE.search(text)
    assert start is not None, (
        "Cannot locate `Step 4b` start marker in build-wheels-bundle.sh — "
        "if the section was renamed, update _STEP4B_BEGIN_RE."
    )
    assert end is not None and end.start() > start.start(), (
        "Cannot locate `Expected critical wheels` end marker after Step 4b — "
        "if the section was renamed, update _STEP4B_END_RE."
    )
    return text[start.start(): end.start()]


def _run_step4b_sandbox(
    tmp_path: Path,
    checksums_content: str | None,
    wheel_files: dict[str, bytes],
) -> subprocess.CompletedProcess[str]:
    """Run the real Step 4b block against a sandbox.

    Args:
        checksums_content: full text of wheels-checksums.txt (or None to skip
            creating it — exercises the missing-file branch).
        wheel_files: {filename: bytes} dropped under $WHEELS_DIR.

    Returns the subprocess result. Caller asserts on returncode."""
    wheels_dir = tmp_path / "InstallNexe.app" / "Contents" / "Resources" / "wheels"
    wheels_dir.mkdir(parents=True)
    for name, data in wheel_files.items():
        (wheels_dir / name).write_bytes(data)

    project_root = tmp_path
    installer_dir = project_root / "installer"
    installer_dir.mkdir()
    if checksums_content is not None:
        (installer_dir / "wheels-checksums.txt").write_text(
            checksums_content, encoding="utf-8"
        )

    block = _extract_step4b_block()
    # Wrapper sets `set -euo pipefail` to mirror the real script's top-of-file
    # invariant, then defines $WHEELS_DIR and $PROJECT_ROOT and runs the
    # extracted block. The block itself defines _sha256() and the loop.
    wrapper = (
        "#!/bin/bash\n"
        "set -euo pipefail\n"
        f'WHEELS_DIR="{wheels_dir}"\n'
        f'PROJECT_ROOT="{project_root}"\n'
        f"{block}\n"
    )
    runner = tmp_path / "step4b_runner.sh"
    runner.write_text(wrapper, encoding="utf-8")

    return subprocess.run(
        ["bash", str(runner)],
        check=False,
        capture_output=True,
        text=True,
    )


def test_step4b_aborts_on_missing_checksums_file(tmp_path: Path) -> None:
    """Finding 1: deleting wheels-checksums.txt MUST abort the build, not
    print a WARN and continue. Otherwise removing the pin file is a one-line
    way to disable the entire B8 supply-chain check."""
    result = _run_step4b_sandbox(
        tmp_path,
        checksums_content=None,
        wheel_files={},
    )
    assert result.returncode != 0, (
        "Build script accepted a missing wheels-checksums.txt — "
        "the supply-chain check can be silently disabled by deleting the file."
        f"\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert result.returncode == 6, (
        f"Expected exit 6 (missing checksums file), got {result.returncode}."
        f"\nstderr: {result.stderr}"
    )


def test_step4b_aborts_on_empty_checksums_file(tmp_path: Path) -> None:
    """Finding 2: a file containing only comments (or zero non-comment lines)
    MUST abort. Otherwise truncating/blanking the file silently passes the
    check with zero wheels actually verified."""
    only_comments = (
        "# wheels-checksums.txt — header only, no active pins\n"
        "# This is what an attacker-truncated file might look like.\n"
        "\n"
    )
    result = _run_step4b_sandbox(
        tmp_path,
        checksums_content=only_comments,
        wheel_files={},
    )
    assert result.returncode != 0, (
        "Build script accepted a comments-only checksums file with zero "
        "verifications — the supply-chain check can be bypassed by truncation."
        f"\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert result.returncode == 10, (
        f"Expected exit 10 (zero verifications), got {result.returncode}."
        f"\nstderr: {result.stderr}"
    )


def test_step4b_handles_missing_trailing_newline(tmp_path: Path) -> None:
    """Finding 3: `while read` returns 1 on EOF and silently drops the last
    line if the file has no trailing newline. Without `|| [ -n "$line" ]`
    the LAST pinned wheel is never verified. Test: write a checksums file
    with NO trailing newline whose last line points to a sandbox file with
    a wrong SHA — the real loop must still catch it."""
    fake_wheel_name = "torch-2.11.0-cp312-cp312-macosx_11_0_arm64.whl"
    fake_bytes = b"\x00" * 1024  # SHA will not match the canonical pin

    # Use the canonical pinned hash from the real checksums file as the
    # "expected" — guaranteed not to match the fake bytes.
    canonical_pins = _read_active_pins()
    torch_sha = next(sha for sha, name in canonical_pins if name.startswith("torch-"))

    # No trailing newline on purpose.
    content_no_newline = f"{torch_sha}  {fake_wheel_name}"
    assert not content_no_newline.endswith("\n")

    result = _run_step4b_sandbox(
        tmp_path,
        checksums_content=content_no_newline,
        wheel_files={fake_wheel_name: fake_bytes},
    )
    assert result.returncode == 8, (
        "Build script silently skipped the LAST pinned wheel when the "
        "checksums file lacked a trailing newline — `while read` EOF bug."
        f"\nreturncode={result.returncode}\nstderr: {result.stderr}"
    )


def test_step4b_rejects_tampered_wheel(tmp_path: Path) -> None:
    """Finding 4: this is the in-CI replacement for a live-bundle tamper test.
    Drops a random-bytes file at the pinned torch filename, runs the REAL
    Step 4b block (extracted from build-wheels-bundle.sh) against it, and
    asserts exit 8 (SHA256 mismatch). Unlike the `shasum -c` test, this
    exercises the actual code path in the build script."""
    canonical_pins = _read_active_pins()
    torch_sha, torch_name = next(
        (sha, name) for sha, name in canonical_pins if name.startswith("torch-")
    )

    checksums_content = f"{torch_sha}  {torch_name}\n"
    tampered = secrets.token_bytes(8192)
    # Belt-and-braces: random bytes don't match the pinned SHA.
    actual_sha = hashlib.sha256(tampered).hexdigest()
    assert actual_sha != torch_sha

    result = _run_step4b_sandbox(
        tmp_path,
        checksums_content=checksums_content,
        wheel_files={torch_name: tampered},
    )
    assert result.returncode == 8, (
        "Build script's manual SHA loop did NOT reject a tampered wheel at "
        "the pinned filename — supply-chain check is broken."
        f"\nreturncode={result.returncode}\nstderr: {result.stderr}"
    )
    assert "SHA256 mismatch" in result.stderr, (
        "Mismatch error message missing from stderr — diagnostic regressed."
    )


def test_step4b_rejects_path_traversal_in_wheel_name(tmp_path: Path) -> None:
    """Finding 5: defense-in-depth. A wheel_name with `..` or `/` in the
    checksums file MUST be rejected. Per threat model (in-repo file, build
    time) this is not exploitable today, but the check costs one `case`
    statement and matches the B8 hardening framing."""
    # Fake hash; it doesn't matter — the path check should fire first.
    checksums_content = (
        "0000000000000000000000000000000000000000000000000000000000000000  ../escape.whl\n"
    )
    result = _run_step4b_sandbox(
        tmp_path,
        checksums_content=checksums_content,
        wheel_files={},
    )
    assert result.returncode == 9, (
        f"Expected exit 9 (path traversal rejected), got {result.returncode}."
        f"\nstderr: {result.stderr}"
    )


def test_step4b_accepts_legitimate_pin(tmp_path: Path) -> None:
    """Positive control: the loop MUST accept a wheel whose actual SHA
    matches the pin. Without this control, all the negative-path tests
    above could pass simply because the loop always exits non-zero."""
    payload = b"this is the legitimate wheel content (test fixture)"
    expected_sha = hashlib.sha256(payload).hexdigest()
    fake_name = "torch-2.11.0-cp312-cp312-macosx_11_0_arm64.whl"
    checksums_content = f"{expected_sha}  {fake_name}\n"

    result = _run_step4b_sandbox(
        tmp_path,
        checksums_content=checksums_content,
        wheel_files={fake_name: payload},
    )
    assert result.returncode == 0, (
        "Step 4b rejected a wheel whose SHA matches the pin — false positive."
        f"\nreturncode={result.returncode}\nstderr: {result.stderr}"
    )
    assert "1 pinned wheel(s) verified" in result.stdout, (
        "Verified-count reporting regressed."
    )
