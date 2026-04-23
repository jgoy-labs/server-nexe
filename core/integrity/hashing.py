"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/integrity/hashing.py
Description: SHA256 helpers + ``verify_sha256`` policy entry point.

Supply-chain integrity primitives shared by the installer (model weight
verification), the build-time scripts (manifest generation for the DMG
fastembed bundle) and the memory pre-computed KB loader. Extracted in
2026-04-23 from ``memory/memory/precomputed_loader.py`` (the KB patron
already in production) so that a single implementation covers every
download surface without duplication.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from typing import Callable, Iterable, Optional, Tuple

logger = logging.getLogger(__name__)

# Hex digest of a SHA256 — 64 lowercase hex characters.
_HEX_RE = re.compile(r"^[0-9a-f]{64}$")

# Streaming chunk size for file reads; mirrors the value used in the KB
# loader, tuned to keep memory flat on multi-GB weights without sacrificing
# throughput on typical Apple Silicon SSDs.
_READ_CHUNK = 65536


class HashMismatchError(RuntimeError):
    """Raised when a downloaded artefact does not match its expected SHA256.

    Carries the offending artefact identifier plus both hashes so the
    installer (GUI + CLI) can log a precise, non-leaking error and tell the
    user exactly what to retry.
    """

    def __init__(
        self,
        artifact: str,
        expected: str,
        actual: str,
        *,
        details: str = "",
    ) -> None:
        self.artifact = artifact
        self.expected = expected
        self.actual = actual
        self.details = details
        parts = [
            f"SHA256 mismatch for {artifact!r}:",
            f"  expected: {expected}",
            f"  actual:   {actual}",
        ]
        if details:
            parts.append(f"  {details}")
        super().__init__("\n".join(parts))


# ═══════════════════════════════════════════════════════════════════════
# Digest primitives
# ═══════════════════════════════════════════════════════════════════════


def sha256_of_bytes(data: bytes) -> str:
    """Return the hex SHA256 of an in-memory byte string."""
    return hashlib.sha256(data).hexdigest()


def sha256_of_file(path: Path) -> str:
    """Return the hex SHA256 of ``path``, read in 64 KB chunks.

    ``FileNotFoundError`` is raised for missing files — callers typically
    want a loud failure, not a silent fallback to an empty-file digest.
    """
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(_READ_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def _default_include_filter(rel_path: str) -> bool:
    """Skip any entry whose relative path contains a dot-prefixed component.

    Hugging Face's ``snapshot_download`` sprinkles ``.lock`` and
    ``.no_exist/`` artefacts inside ``local_dir``; macOS adds ``.DS_Store``;
    the KB loader adds ``.embeddings/``. None of these belong to the
    reproducible contents of a model snapshot, and including them would
    make the digest depend on the caller's filesystem state rather than on
    the model itself.
    """
    return not any(part.startswith(".") for part in Path(rel_path).parts)


def sha256_of_dir(
    root: Path,
    *,
    include_filter: Optional[Callable[[str], bool]] = None,
) -> str:
    """Return a deterministic hex SHA256 of the contents of ``root``.

    The digest folds ``(relative_posix_path, file_bytes)`` pairs in sorted
    order — filesystem metadata (mtime, permissions, inode order) does not
    contribute. This is the function the installer uses to pin the whole
    Hugging Face snapshot directory returned by ``snapshot_download``.

    Parameters
    ----------
    root:
        Directory to hash. Must exist; missing roots raise
        ``FileNotFoundError`` so callers never silently trust an empty
        digest.
    include_filter:
        ``callable(rel_posix_path) -> bool`` applied to each file's path
        relative to ``root``. When omitted, the default filter skips any
        dot-prefixed component (see :func:`_default_include_filter`). Pass
        ``lambda _: True`` to hash everything verbatim.
    """
    if not root.is_dir():
        raise FileNotFoundError(f"Not a directory: {root}")
    flt = include_filter if include_filter is not None else _default_include_filter
    # ``Path.rglob`` combined with ``is_file`` happily follows symlinks whose
    # target sits anywhere on the filesystem. A tampered snapshot directory
    # could therefore plant a symlink pointing at ``/etc/passwd`` (or any
    # other file whose digest the attacker knows) and have its bytes fold
    # into this hash — the catalog pin would end up matching a value
    # computed from bytes the attacker controls. Resolve and require the
    # target to stay inside ``root`` so the policy matches the one already
    # applied in ``verify_embedding_bundle._find_bundle_file``.
    root_resolved = root.resolve()
    h = hashlib.sha256()
    for p in sorted(x for x in root.rglob("*") if x.is_file()):
        rel = p.relative_to(root).as_posix()
        if not flt(rel):
            continue
        try:
            resolved = p.resolve()
        except (OSError, RuntimeError):
            # Broken symlink or resolution loop — skip silently; if the
            # file was supposed to contribute to the hash, a downstream
            # verify_sha256 will flag the resulting digest mismatch.
            continue
        try:
            resolved.relative_to(root_resolved)
        except ValueError:
            logger.warning(
                "sha256_of_dir: symlink %s escapes root %s — skipped.",
                p, root_resolved,
            )
            continue
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        with p.open("rb") as f:
            for chunk in iter(lambda: f.read(_READ_CHUNK), b""):
                h.update(chunk)
        h.update(b"\0")
    return h.hexdigest()


def sha256_stream_download(chunks: Iterable[bytes]) -> Tuple[str, int]:
    """Fold an iterable of byte chunks into a ``(digest, total_bytes)`` pair.

    Meant for download pipelines that receive the body as a generator
    (``requests``, ``httpx`` streams): hash-as-you-go so the full payload
    never materialises in memory and the check runs in a single pass.
    """
    h = hashlib.sha256()
    total = 0
    for chunk in chunks:
        h.update(chunk)
        total += len(chunk)
    return h.hexdigest(), total


# ═══════════════════════════════════════════════════════════════════════
# Policy — the single entry point the installer calls after each download
# ═══════════════════════════════════════════════════════════════════════


def _normalise_hex(value: str) -> str:
    return value.strip().lower()


def _check_hex(value: str, label: str) -> None:
    if not _HEX_RE.match(value):
        raise ValueError(
            f"Invalid SHA256 digest for {label}: expected 64 hex chars, got {value!r}"
        )


def verify_sha256(
    actual: str,
    expected: Optional[str],
    *,
    artifact: str,
    allow_missing: bool = True,
    details: str = "",
) -> bool:
    """Compare ``actual`` against ``expected`` under the installer policy.

    Returns
    -------
    bool
        * ``True``  — both hashes are present and equal (strict policy OK).
        * ``False`` — ``expected is None`` and ``allow_missing=True``: the
          catalog carries no pin for this artefact yet (legacy). A warning
          is logged so the gap is visible. Callers treat a ``False`` return
          as a degraded path and typically emit a user-visible
          ``⚠️ model not pinned`` notice.

    Raises
    ------
    ValueError
        ``actual`` is not a syntactically valid SHA256 hex digest, or
        ``expected`` is present but syntactically invalid.
    HashMismatchError
        Both hashes are present and differ, OR ``expected is None`` with
        ``allow_missing=False`` (strict mode used by CI-time build checks).

    Comparison is case-insensitive and strips surrounding whitespace:
    ``ollama show --json`` emits lowercase digests with a trailing newline,
    some build tools emit uppercase, and manifest JSON files round-trip
    through ``json.dumps`` — callers should not have to normalise.
    """
    actual_norm = _normalise_hex(actual)
    _check_hex(actual_norm, f"{artifact} (actual)")

    if expected is None:
        if allow_missing:
            logger.warning(
                "Integrity: no SHA256 pin for %r — accepted in legacy mode. "
                "Observed digest %s; add it to the catalog to close this gap.",
                artifact, actual_norm,
            )
            return False
        raise HashMismatchError(
            artifact=artifact,
            expected="<missing>",
            actual=actual_norm,
            details=(
                details
                or "Strict mode requires a pinned SHA256 for this artifact."
            ),
        )

    expected_norm = _normalise_hex(expected)
    _check_hex(expected_norm, f"{artifact} (expected)")

    if actual_norm != expected_norm:
        raise HashMismatchError(
            artifact=artifact,
            expected=expected_norm,
            actual=actual_norm,
            details=details,
        )
    return True


__all__ = [
    "HashMismatchError",
    "sha256_of_bytes",
    "sha256_of_dir",
    "sha256_of_file",
    "sha256_stream_download",
    "verify_sha256",
]
