"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: installer/download_verify.py
Description: Post-download SHA256 enforcement for LLM weights (F4.1 audit
             DoD-AUD-SX-0423 §2.7).

Shared by the CLI headless installer (``install_headless.py``) and the
interactive wizard path (``installer_catalog.select_model`` + friends).
A single ``verify_download_integrity`` entry point covers the three
backends:

  * ``mlx``    — the local ``snapshot_download`` directory.
  * ``gguf``   — the single .gguf file returned by ``curl``.
  * ``ollama`` — the manifest digest reported by ``ollama show --json``.

On a mismatch this module raises :class:`DownloadIntegrityError` with
actionable retry instructions. On an unpinned catalog entry (the current
legacy mode for every model) it returns ``False`` so the caller can
surface a visible ``⚠️ not pinned`` notice without aborting the install.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from core.integrity.hashing import (
    HashMismatchError,
    sha256_of_dir,
    sha256_of_file,
    verify_sha256,
)
from installer.installer_catalog_data import (
    VALID_SHA256_ENGINES,
    get_expected_sha256,
)

logger = logging.getLogger(__name__)

# Seconds; ``ollama show --json`` is a local call and returns in
# milliseconds on a warm daemon. Ten seconds leaves ample headroom for a
# cold boot without letting a wedged daemon block the installer.
_OLLAMA_SHOW_TIMEOUT = 10


class DownloadIntegrityError(RuntimeError):
    """Raised when a freshly downloaded artefact fails SHA256 verification.

    The installer (CLI + GUI) turns the exception message into user-facing
    text; it includes both digests and an engine-specific retry recipe so
    the user can repeat the download in isolation. The partial artefact is
    preserved on disk on purpose — post-mortem is easier with the failed
    bytes than without.
    """

    def __init__(
        self,
        artifact: str,
        message: str,
        *,
        cause: Optional[Exception] = None,
    ) -> None:
        """Initialize with the failed artifact name, message, and optional cause."""
        self.artifact = artifact
        self.cause = cause
        super().__init__(message)


# ═══════════════════════════════════════════════════════════════════════
# Retry text — engine-specific so the UI can paste it verbatim.
# ═══════════════════════════════════════════════════════════════════════


def _retry_instructions(
    engine: str, model_id: str, target: Optional[Path] = None
) -> str:
    if engine == "ollama":
        return (
            "To retry:\n"
            f"  ollama rm {model_id}\n"
            f"  ollama pull {model_id}\n"
        )
    # mlx/gguf: prefer the real on-disk path (verify_download_integrity always
    # passes `target`). Fall back to the legacy placeholder only when the
    # caller didn't provide one (defensive — never hit in practice).
    if engine == "gguf":
        filename = model_id.split("/")[-1]
        location = str(target) if target is not None else f"<install>/storage/models/{filename}"
        return (
            "To retry:\n"
            f"  rm {location}\n"
            "  ./nexe model pull\n"
        )
    if engine == "mlx":
        local_name = model_id.split("/")[-1]
        location = str(target) if target is not None else f"<install>/storage/models/{local_name}"
        return (
            "To retry:\n"
            f"  rm -rf {location}\n"
            "  ./nexe model pull\n"
        )
    # Defensive: unreachable — dispatch already rejects unknown engines.
    return ""


# ═══════════════════════════════════════════════════════════════════════
# Ollama — read the manifest digest via the local daemon.
# ═══════════════════════════════════════════════════════════════════════


def _resolve_ollama_bin(ollama_bin: str, model_id: str) -> Optional[str]:
    """Return the resolved ollama binary path or None if not found."""
    if shutil.which(ollama_bin):
        return ollama_bin
    if Path(ollama_bin).is_file():
        return ollama_bin
    logger.warning(
        "Integrity: ollama binary not found at %r — cannot verify digest for %r",
        ollama_bin, model_id,
    )
    return None


def _run_ollama_show(resolved: str, model_id: str) -> Optional[str]:
    """Run ``ollama show --json`` and return stdout or None on failure."""
    try:
        result = subprocess.run(  # nosec B603: resolved is validated via shutil.which/Path.is_file; model_id is from internal MODEL_CATALOG (supply chain trust)
            [resolved, "show", "--json", model_id],
            capture_output=True,
            text=True,
            timeout=_OLLAMA_SHOW_TIMEOUT,
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        logger.warning(
            "Integrity: `ollama show --json %s` failed (%s) — cannot verify digest",
            model_id, e,
        )
        return None
    if result.returncode != 0 or not result.stdout.strip():
        logger.warning(
            "Integrity: `ollama show --json %s` returned %d; stderr=%s — cannot verify digest",
            model_id,
            result.returncode,
            (result.stderr or "").strip()[:200],
        )
        return None
    return result.stdout


def _parse_ollama_digest(stdout: str, model_id: str) -> Optional[str]:
    """Parse the digest field from ollama show JSON output."""
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as e:
        logger.warning(
            "Integrity: `ollama show --json %s` emitted invalid JSON (%s) — cannot verify digest",
            model_id, e,
        )
        return None
    digest = (
        (payload.get("details") or {}).get("digest")
        or payload.get("digest")
        or None
    )
    if digest is None:
        logger.warning(
            "Integrity: `ollama show --json %s` has no details.digest — older Ollama? "
            "Falling back to legacy mode.",
            model_id,
        )
        return None
    # Schema drift: some Ollama versions emit ``digest`` as a structured
    # object (dict/list) instead of a string.
    if not isinstance(digest, str):
        logger.warning(
            "Integrity: `ollama show --json %s` returned non-string digest %r — "
            "falling back to legacy mode.",
            model_id, type(digest).__name__,
        )
        return None
    # Normalise away the optional ``sha256:`` prefix some versions emit.
    if digest.lower().startswith("sha256:"):
        digest = digest[len("sha256:"):]
    return digest


def get_ollama_digest(
    model_id: str,
    *,
    ollama_bin: str = "ollama",
) -> Optional[str]:
    """Return the SHA256 digest reported by ``ollama show --json <model>``.

    Accepted schemas:
      * recent builds → ``{"details": {"digest": "<hex>"}}``
      * older builds  → ``{"digest": "<hex>"}``

    Some Ollama versions prefix the hex with ``sha256:``; that prefix is
    stripped before returning. Any failure (binary missing, non-zero exit,
    invalid JSON, timeout, or absent ``digest`` field) is logged as a
    WARNING and returns ``None`` — the installer treats that as the
    legacy condition ("verify not available for this environment") rather
    than as a mismatch.
    """
    resolved = _resolve_ollama_bin(ollama_bin, model_id)
    if resolved is None:
        return None
    stdout = _run_ollama_show(resolved, model_id)
    if stdout is None:
        return None
    return _parse_ollama_digest(stdout, model_id)


# ═══════════════════════════════════════════════════════════════════════
# Dispatch — one place per engine to compute the actual digest.
# ═══════════════════════════════════════════════════════════════════════


def _compute_actual(
    engine: str,
    target: Path,
    *,
    ollama_bin: str,
    model_id: str,
) -> Optional[str]:
    """Compute the actual SHA256 digest of a downloaded artifact by engine type."""
    if engine == "mlx":
        return sha256_of_dir(target)
    if engine == "gguf":
        return sha256_of_file(target)
    if engine == "ollama":
        return get_ollama_digest(model_id, ollama_bin=ollama_bin)
    raise ValueError(
        f"Unknown engine for integrity check: {engine!r}. "
        f"Expected one of: {sorted(VALID_SHA256_ENGINES)}"
    )


# ═══════════════════════════════════════════════════════════════════════
# Public entry point — call this after each download.
# ═══════════════════════════════════════════════════════════════════════


def verify_download_integrity(
    engine: str,
    model_id: str,
    target: Path,
    *,
    ollama_bin: str = "ollama",
) -> bool:
    """Verify the SHA256 of a freshly downloaded artefact against the catalog.

    Returns
    -------
    bool
        * ``True``  — a pin exists AND the downloaded artefact matches it.
        * ``False`` — the catalog has no pin for this ``(engine, model_id)``
          OR the actual digest could not be computed (e.g. missing
          ``ollama`` binary, older daemon without a ``digest`` field).
          The caller has already seen a WARNING in the log and should
          continue with the install while surfacing a "not pinned" notice.

    Raises
    ------
    ValueError
        ``engine`` is unknown — a coding bug, not a legacy condition.
    DownloadIntegrityError
        A pin exists but the artefact's digest does not match. The
        artefact is preserved on disk (we never delete partial downloads
        automatically — post-mortem is easier with the bytes than
        without, and the user can ``rm`` deliberately).
    """
    if engine not in VALID_SHA256_ENGINES:
        raise ValueError(
            f"Unknown engine for integrity check: {engine!r}. "
            f"Expected one of: {sorted(VALID_SHA256_ENGINES)}"
        )

    expected = get_expected_sha256(engine, model_id)
    actual = _compute_actual(engine, target, ollama_bin=ollama_bin, model_id=model_id)
    if actual is None:
        # Could not determine the actual digest — Ollama-only path when the
        # daemon is absent or too old. Treat as legacy; the user sees a
        # warning already.
        return False

    try:
        matched = verify_sha256(
            actual,
            expected,
            artifact=f"{engine}:{model_id}",
            allow_missing=True,
        )
    except HashMismatchError as exc:
        msg = (
            f"SHA256 mismatch for {engine} model {model_id!r}.\n"
            f"  expected: {exc.expected}\n"
            f"  actual:   {exc.actual}\n"
            f"The downloaded artefact has been preserved at {target} for inspection.\n"
            f"{_retry_instructions(engine, model_id, target)}"
        )
        raise DownloadIntegrityError(
            artifact=model_id, message=msg, cause=exc
        ) from exc
    return matched


# ═══════════════════════════════════════════════════════════════════════
# Embedding bundle — DMG-shipped fastembed model
# ═══════════════════════════════════════════════════════════════════════
#
# The build-embedding-bundle.sh script writes an integrity manifest next
# to the ONNX + tokenizer + config files shipped inside the DMG:
#
#   {
#     "schema_version": 1,
#     "model_name":     "sentence-transformers/paraphrase-multilingual-mpnet-base-v2",
#     "generated_at":   "2026-04-23T…Z",
#     "files": {
#       "model.onnx":      "<sha256>",
#       "tokenizer.json":  "<sha256>",
#       "config.json":     "<sha256>"
#     }
#   }
#
# ``verify_embedding_bundle`` re-hashes the three files at copy time. A
# tampered or missing file raises DownloadIntegrityError. A missing
# manifest — older DMGs built before the integrity check — returns False so pre-release
# installs keep working with a visible warning.


_BUNDLE_MANIFEST_FILENAME = "embeddings.manifest.json"


def _find_bundle_file(bundle_dir: Path, filename: str) -> Optional[Path]:
    """Locate ``filename`` inside ``bundle_dir`` without chasing HF-cache noise.

    The fastembed bundle stores the real file either at the root of the
    bundle directory (after the flattening step) or inside
    ``models--<org>--<name>/snapshots/<rev>/`` as a symlink pointing at
    ``blobs/<sha>``. We accept any depth but skip dotfile components so
    that ``.locks`` and friends never shadow a real match.

    Symlink safety: HF hub links always point at ``blobs/`` *inside* the
    same model dir. A tampered bundle could replace one with a symlink
    to ``/etc/passwd`` (say) that happens to hash to the manifest pin.
    We resolve the link and reject any target that escapes ``bundle_dir``
    — only files physically inside the bundle are accepted.
    """
    bundle_root = bundle_dir.resolve()
    for p in bundle_dir.rglob(filename):
        rel_parts = p.relative_to(bundle_dir).parts
        if any(part.startswith(".") for part in rel_parts):
            continue
        try:
            resolved = p.resolve()
        except (OSError, RuntimeError):
            # Broken symlink or resolution loop — skip silently and let
            # verify_embedding_bundle raise a clean "missing file" later.
            continue
        try:
            resolved.relative_to(bundle_root)
        except ValueError:
            logger.warning(
                "Integrity: symlink %s escapes bundle root (%s); refusing to follow.",
                p, bundle_root,
            )
            continue
        if resolved.is_file():
            return resolved
    return None


def verify_embedding_bundle(bundle_dir: Path) -> bool:
    """Check the integrity manifest of a DMG-shipped fastembed bundle.

    Returns
    -------
    bool
        * ``True``  — manifest present, every listed file found, every
          SHA256 matches.
        * ``False`` — bundle missing, manifest absent (pre-F4.1 DMG) or
          the ``files`` map is empty. A WARNING is logged in those cases
          so operators see the gap.

    Raises
    ------
    DownloadIntegrityError
        The manifest is unreadable, a listed file is missing, or a file's
        SHA256 does not match. The caller (``_seed_fastembed_cache``) must
        not copy the bundle into the user's cache when this is raised.
    """
    if not bundle_dir.is_dir():
        return False

    manifest_path = bundle_dir / _BUNDLE_MANIFEST_FILENAME
    if not manifest_path.is_file():
        logger.warning(
            "Embedding bundle at %s has no integrity manifest (%s) — "
            "legacy DMG (pre-F4.1). Proceeding without SHA256 enforcement.",
            bundle_dir, _BUNDLE_MANIFEST_FILENAME,
        )
        return False

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise DownloadIntegrityError(
            artifact="embedding-bundle",
            message=(
                f"Cannot read embedding bundle manifest at {manifest_path}: {e}. "
                "The DMG bundle may be corrupted; re-download the installer."
            ),
            cause=e,
        ) from e

    files = manifest.get("files") or {}
    if not files:
        logger.warning(
            "Embedding bundle manifest at %s has no file entries — "
            "legacy or malformed manifest. Proceeding without enforcement.",
            manifest_path,
        )
        return False

    for rel_name, expected in files.items():
        found = _find_bundle_file(bundle_dir, rel_name)
        if found is None:
            raise DownloadIntegrityError(
                artifact="embedding-bundle",
                message=(
                    f"Expected file {rel_name!r} is missing from the embedding "
                    f"bundle at {bundle_dir}. The DMG may be corrupted or "
                    f"mis-built; re-download the installer."
                ),
            )
        actual = sha256_of_file(found)
        try:
            verify_sha256(
                actual,
                expected,
                artifact=f"embedding-bundle:{rel_name}",
                allow_missing=False,
            )
        except HashMismatchError as exc:
            raise DownloadIntegrityError(
                artifact="embedding-bundle",
                message=(
                    f"SHA256 mismatch for {rel_name} inside embedding bundle "
                    f"({bundle_dir}):\n"
                    f"  expected: {exc.expected}\n"
                    f"  actual:   {exc.actual}\n"
                    f"The bundle is either corrupted or tampered. "
                    "Re-download the DMG from the official source."
                ),
                cause=exc,
            ) from exc
    return True


__all__ = [
    "DownloadIntegrityError",
    "get_ollama_digest",
    "verify_download_integrity",
    "verify_embedding_bundle",
]
