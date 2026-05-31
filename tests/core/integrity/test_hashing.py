"""
────────────────────────────────────
Server Nexe
Location: core/integrity/tests/test_hashing.py
Description: Unit tests for core.integrity.hashing — SHA256 helpers and the
             verify_sha256 policy function used by the installer to abort on
             supply-chain mismatches.

             TDD RED → GREEN flow for internal security-review finding AUD-INT-001 §2.7
             (SHA256 pinning of downloaded model weights).
────────────────────────────────────
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

import pytest

from core.integrity.hashing import (
    HashMismatchError,
    sha256_of_bytes,
    sha256_of_dir,
    sha256_of_file,
    sha256_stream_download,
    verify_sha256,
)


# ════════════════════════════════════════════════════════════════════════
# sha256_of_bytes
# ════════════════════════════════════════════════════════════════════════


def test_sha256_of_bytes_known_vector() -> None:
    """NIST test vector — the empty string hashes to e3b0c4...b855."""
    expected = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    assert sha256_of_bytes(b"") == expected


def test_sha256_of_bytes_ascii() -> None:
    assert sha256_of_bytes(b"abc") == (
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )


def test_sha256_of_bytes_determinism() -> None:
    data = b"supply-chain integrity"
    assert sha256_of_bytes(data) == sha256_of_bytes(data)


# ════════════════════════════════════════════════════════════════════════
# sha256_of_file
# ════════════════════════════════════════════════════════════════════════


def test_sha256_of_file_matches_known_content(tmp_path: Path) -> None:
    payload = b"hello, nexe"
    f = tmp_path / "sample.bin"
    f.write_bytes(payload)
    assert sha256_of_file(f) == hashlib.sha256(payload).hexdigest()


def test_sha256_of_file_large_content_streamed(tmp_path: Path) -> None:
    """Force the internal chunked read loop (>64 KB)."""
    # 256 KB deterministic payload — more than 4 read chunks of 64 KB.
    payload = (b"A" * 65536) + (b"B" * 65536) + (b"C" * 65536) + (b"D" * 65536)
    f = tmp_path / "large.bin"
    f.write_bytes(payload)
    expected = hashlib.sha256(payload).hexdigest()
    assert sha256_of_file(f) == expected


def test_sha256_of_file_missing_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        sha256_of_file(tmp_path / "does-not-exist.bin")


# ════════════════════════════════════════════════════════════════════════
# sha256_of_dir — deterministic directory hash
# ════════════════════════════════════════════════════════════════════════


def _mk_tree(root: Path, files: dict[str, bytes]) -> None:
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)


def test_sha256_of_dir_determinism_same_tree(tmp_path: Path) -> None:
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    files = {"config.json": b'{"k": 1}', "sub/tokenizer.json": b"{}"}
    _mk_tree(a, files)
    _mk_tree(b, files)
    assert sha256_of_dir(a) == sha256_of_dir(b)


def test_sha256_of_dir_changes_with_content(tmp_path: Path) -> None:
    root = tmp_path / "d"
    root.mkdir()
    (root / "config.json").write_bytes(b"v1")
    h1 = sha256_of_dir(root)
    (root / "config.json").write_bytes(b"v2")
    h2 = sha256_of_dir(root)
    assert h1 != h2


def test_sha256_of_dir_ignores_dotfiles_by_default(tmp_path: Path) -> None:
    """Hidden files like .lock / .no_exist (HF cache artefacts) must be
    ignored so the manifest stays stable across user environments."""
    root = tmp_path / "d"
    root.mkdir()
    (root / "model.onnx").write_bytes(b"weights")
    h_clean = sha256_of_dir(root)
    (root / ".lock").write_bytes(b"pid=1234")
    (root / ".no_exist" / "stale").parent.mkdir()
    (root / ".no_exist" / "stale").write_bytes(b"stale")
    h_noisy = sha256_of_dir(root)
    assert h_clean == h_noisy


def test_sha256_of_dir_include_filter_overrides_default(tmp_path: Path) -> None:
    """An explicit filter lets the caller include or exclude by path."""
    root = tmp_path / "d"
    root.mkdir()
    (root / "model.onnx").write_bytes(b"weights")
    (root / ".lock").write_bytes(b"pid=1234")
    # Custom filter that INCLUDES the dotfile — hash should differ from default.
    accept_all = lambda rel: True  # noqa: E731
    h_default = sha256_of_dir(root)
    h_all = sha256_of_dir(root, include_filter=accept_all)
    assert h_default != h_all


def test_sha256_of_dir_missing_root_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        sha256_of_dir(tmp_path / "not-here")


def test_sha256_of_dir_empty_dir(tmp_path: Path) -> None:
    root = tmp_path / "empty"
    root.mkdir()
    # Empty dirs hash to the empty-bytes digest — stable across callers.
    assert sha256_of_dir(root) == sha256_of_bytes(b"")


def test_sha256_of_dir_skips_symlink_escape(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A tampered snapshot can plant a symlink pointing outside its root so
    that its bytes fold into the computed digest. ``sha256_of_dir`` must
    treat such entries as absent so the hash only reflects files that
    actually live under ``root`` — matching the policy enforced by
    ``verify_embedding_bundle``.

    The test compares against a clean version of the same tree (no escape
    link). If ``sha256_of_dir`` were still honouring the symlink, the two
    hashes would differ because the external file's bytes would contribute.
    """
    caplog.set_level(logging.WARNING, logger="core.integrity.hashing")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret").write_bytes(b"attacker-controlled-bytes")

    # Clean bundle: just one real file.
    clean = tmp_path / "clean"
    clean.mkdir()
    (clean / "model.bin").write_bytes(b"weights")
    h_clean = sha256_of_dir(clean)

    # Tampered bundle: same legit file + one symlink escaping to outside.
    tampered = tmp_path / "tampered"
    tampered.mkdir()
    (tampered / "model.bin").write_bytes(b"weights")
    (tampered / "evil").symlink_to(outside / "secret")

    h_tampered = sha256_of_dir(tampered)
    assert h_tampered == h_clean, (
        "sha256_of_dir folded an escaping symlink into the digest; "
        "the tampered hash must match the clean one."
    )
    assert any(
        "escapes root" in rec.getMessage() for rec in caplog.records
    )


# ════════════════════════════════════════════════════════════════════════
# sha256_stream_download
# ════════════════════════════════════════════════════════════════════════


def test_sha256_stream_download_matches_bytes_equivalent() -> None:
    chunks = [b"the ", b"quick ", b"brown ", b"fox"]
    full = b"".join(chunks)
    digest, size = sha256_stream_download(chunks)
    assert digest == sha256_of_bytes(full)
    assert size == len(full)


def test_sha256_stream_download_handles_empty_iterator() -> None:
    digest, size = sha256_stream_download(iter(()))
    assert digest == sha256_of_bytes(b"")
    assert size == 0


# ════════════════════════════════════════════════════════════════════════
# verify_sha256 — policy entry point
# ════════════════════════════════════════════════════════════════════════


def test_verify_sha256_match_returns_true() -> None:
    digest = sha256_of_bytes(b"hello")
    assert verify_sha256(digest, digest, artifact="hello.bin") is True


def test_verify_sha256_mismatch_raises(caplog: pytest.LogCaptureFixture) -> None:
    with pytest.raises(HashMismatchError) as excinfo:
        verify_sha256("deadbeef" * 8, "cafebabe" * 8, artifact="model.safetensors")
    err = excinfo.value
    assert err.artifact == "model.safetensors"
    assert err.expected == "cafebabe" * 8
    assert err.actual == "deadbeef" * 8
    # The exception string should include both hashes so operators can debug.
    assert "deadbeef" in str(err)
    assert "cafebabe" in str(err)


def test_verify_sha256_missing_expected_allows_legacy(caplog: pytest.LogCaptureFixture) -> None:
    """Catalog entries without a pinned hash return False (legacy mode) and
    log a warning so operators see the gap — but do not abort."""
    caplog.set_level(logging.WARNING, logger="core.integrity.hashing")
    result = verify_sha256("aa" * 32, None, artifact="gemma3:4b")
    assert result is False
    assert any("gemma3:4b" in rec.getMessage() for rec in caplog.records)
    assert any(rec.levelno == logging.WARNING for rec in caplog.records)


def test_verify_sha256_missing_expected_strict_raises() -> None:
    """When allow_missing=False, a None expected becomes a hard error —
    used in contexts where pinning is mandatory (e.g. CI build checks)."""
    with pytest.raises(HashMismatchError):
        verify_sha256("aa" * 32, None, artifact="required.bin", allow_missing=False)


def test_verify_sha256_case_insensitive() -> None:
    """Operators may paste hashes in mixed case (`ollama show` emits lower
    case, some tools emit upper). Comparison must normalise casing."""
    digest = sha256_of_bytes(b"mixed-case")
    assert verify_sha256(digest.upper(), digest, artifact="a") is True
    assert verify_sha256(digest, digest.upper(), artifact="a") is True


def test_verify_sha256_strips_whitespace() -> None:
    """Hashes copied from manifests or JSON sometimes carry trailing
    newlines; strip to avoid false mismatches."""
    digest = sha256_of_bytes(b"strip-me")
    assert verify_sha256(digest + "\n", "  " + digest, artifact="a") is True


def test_verify_sha256_invalid_format_raises() -> None:
    """Hex strings shorter than 64 chars are almost certainly a catalog
    typo; fail loud instead of accepting them silently."""
    with pytest.raises(ValueError):
        verify_sha256("not-hex", sha256_of_bytes(b"x"), artifact="a")
    with pytest.raises(ValueError):
        verify_sha256(sha256_of_bytes(b"x"), "abc", artifact="a")
