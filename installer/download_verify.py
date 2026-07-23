"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: installer/download_verify.py
Description: Post-download SHA256 enforcement for LLM weights (internal
             security review AUD-INT-001 §2.7).

Shared by the CLI headless installer (``install_headless.py``) and the
interactive wizard path (``installer_catalog.select_model`` + friends).
A single ``verify_download_integrity`` entry point covers the three
backends:

  * ``mlx``    — the local ``snapshot_download`` directory.
  * ``gguf``   — the single .gguf file returned by ``curl``.
  * ``ollama`` — delegated to Ollama's own content-addressed pull. We keep
                 NO client-side pin (ADR B251 / THREAT_MODEL §4.3): Ollama
                 verifies every layer against the manifest digest during
                 ``ollama pull``, and its catalog tags are mutable upstream
                 (a client pin would false-positive on a legitimate
                 re-publish). ``verify_download_integrity`` therefore
                 short-circuits Ollama to a logged ``True``.

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
import os
import sys
from pathlib import Path
from typing import Callable, Optional

from core.integrity.hashing import (
    HashMismatchError,
    sha256_of_dir,
    sha256_of_file,
    verify_sha256,
)
from installer.installer_catalog_data import (
    VALID_SHA256_ENGINES,
    get_expected_mlx_file_hashes,
    get_expected_sha256,
)

logger = logging.getLogger(__name__)


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


class UnpinnedModelError(RuntimeError):
    """Raised when an unpinned artefact is refused install-time consent.

    Replaces the previous silent fail-open (ADR B046b): an MLX/GGUF artefact
    with no integrity pin is never installed silently — the caller obtains
    explicit consent or aborts.
    """


_ALLOW_UNPINNED_ENV = "NEXE_ALLOW_UNPINNED"


def consent_for_unpinned(
    engine: str,
    model_id: str,
    *,
    prompt: Callable[[str], str] = input,
    isatty: Optional[bool] = None,
) -> bool:
    """Decide whether to install an MLX/GGUF artefact that has NO integrity pin.

    Returns ``True`` to proceed; raises :class:`UnpinnedModelError` to abort.
    Policy (ADR B046b) — never a silent fail-open:

      * ``NEXE_ALLOW_UNPINNED`` truthy → proceed (explicit headless/CI opt-in,
        logged at WARNING).
      * an interactive TTY → ask ``[y/N]``; raise on anything but yes.
      * non-interactive without the opt-in → raise (the user can re-run with
        the env var or pin the model).

    Ollama is NOT routed here: its content-addressed pull already verifies
    layer integrity against the manifest (see THREAT_MODEL §4.3).
    """
    if os.environ.get(_ALLOW_UNPINNED_ENV, "").strip().lower() in {"1", "true", "yes"}:
        logger.warning(
            "Installing UNPINNED %s model %r — %s is set; weight integrity is "
            "NOT verified.", engine, model_id, _ALLOW_UNPINNED_ENV,
        )
        return True

    interactive = sys.stdin.isatty() if isatty is None else isatty
    if interactive:
        answer = prompt(
            f"\n⚠️  No integrity pin is available for {engine} model "
            f"{model_id!r}. Install it WITHOUT weight verification? [y/N] "
        ).strip().lower()
        if answer in {"y", "yes"}:
            logger.warning(
                "User consented to unpinned install of %s %r.", engine, model_id)
            return True
        raise UnpinnedModelError(
            f"User declined the unpinned install of {engine} model {model_id!r}."
        )

    raise UnpinnedModelError(
        f"No integrity pin for {engine} model {model_id!r} and no interactive "
        f"terminal to confirm. Re-run with {_ALLOW_UNPINNED_ENV}=1 to allow it "
        f"explicitly, or add a pin to the catalog."
    )


def consent_for_unpinned_deps(
    context: str,
    *,
    prompt: Optional[Callable[[str], str]] = None,
    isatty: Optional[bool] = None,
) -> bool:
    """Decide whether an OFFLINE dependency install may fall back to unpinned
    PyPI after the bundle's no-index install failed (WS8-05).

    Same policy and env var as :func:`consent_for_unpinned` — never a silent
    fail-open: ``NEXE_ALLOW_UNPINNED`` truthy → proceed (WARNING); interactive
    TTY → ask ``[y/N]``; non-interactive without the opt-in → raise.
    """
    if os.environ.get(_ALLOW_UNPINNED_ENV, "").strip().lower() in {"1", "true", "yes"}:
        logger.warning(
            "Offline install of %s falls back to UNPINNED PyPI — %s is set; "
            "the bundle supply-chain guarantee is lost.", context, _ALLOW_UNPINNED_ENV,
        )
        return True

    interactive = sys.stdin.isatty() if isatty is None else isatty
    if interactive:
        ask = input if prompt is None else prompt
        answer = ask(
            f"\n⚠️  Offline install of {context} is incomplete. Fall back to "
            f"PyPI WITHOUT the bundle's integrity guarantee? [y/N] "
        ).strip().lower()
        if answer in {"y", "yes"}:
            logger.warning("User consented to unpinned PyPI fallback for %s.", context)
            return True
        raise UnpinnedModelError(
            f"User declined the unpinned PyPI fallback for {context}."
        )

    raise UnpinnedModelError(
        f"Offline install of {context} failed and there is no interactive "
        f"terminal to confirm the unpinned PyPI fallback. Re-run with "
        f"{_ALLOW_UNPINNED_ENV}=1 to allow it explicitly, or repair the "
        f"offline bundle."
    )


# ═══════════════════════════════════════════════════════════════════════
# Retry text — engine-specific so the UI can paste it verbatim.
# ═══════════════════════════════════════════════════════════════════════


def _retry_instructions(
    engine: str, model_id: str, target: Optional[Path] = None
) -> str:
    # mlx/gguf: prefer the real on-disk path (verify_download_integrity always
    # passes `target`). Fall back to the legacy placeholder only when the
    # caller didn't provide one (defensive — never hit in practice).
    if engine == "gguf":
        filename = model_id.split("/")[-1]
        location = str(target) if target is not None else f"<install>/storage/models/{filename}"
        return (
            "To retry:\n"
            f"  rm {location}\n"
            "  ./nexe model install <model-name>\n"
        )
    if engine == "mlx":
        local_name = model_id.split("/")[-1]
        location = str(target) if target is not None else f"<install>/storage/models/{local_name}"
        return (
            "To retry:\n"
            f"  rm -rf {location}\n"
            "  ./nexe model install <model-name>\n"
        )
    # Defensive: unreachable — dispatch already rejects unknown engines.
    return ""


# ═══════════════════════════════════════════════════════════════════════
# Dispatch — one place per engine to compute the actual digest.
# Ollama is not here: it is short-circuited in verify_download_integrity
# (delegated to Ollama's content-addressed pull, ADR B251).
# ═══════════════════════════════════════════════════════════════════════


def _compute_actual(engine: str, target: Path) -> Optional[str]:
    """Compute the actual SHA256 digest of a downloaded artifact by engine type."""
    if engine == "mlx":
        return sha256_of_dir(target)
    if engine == "gguf":
        return sha256_of_file(target)
    raise ValueError(
        f"Unknown engine for integrity check: {engine!r}. "
        f"Expected one of: {sorted(VALID_SHA256_ENGINES)}"
    )


def _locate_in_dir(root: Path, rfilename: str) -> Optional[Path]:
    """Find ``rfilename`` inside ``root`` (snapshot layout or HF-cache), safely.

    Tries the natural snapshot path ``root/rfilename`` first, then falls back
    to a basename search at any depth (HF cache stores the real bytes under
    ``snapshots/<rev>/`` symlinked from ``blobs/``). Symlink safety mirrors
    ``_find_bundle_file``: the resolved target must stay inside ``root`` so a
    tampered snapshot cannot point a pinned name at an attacker-known file.
    """
    root_resolved = root.resolve()

    def _safe(p: Path) -> Optional[Path]:
        try:
            resolved = p.resolve()
            resolved.relative_to(root_resolved)
        except (ValueError, OSError):
            return None
        return p if resolved.is_file() else None

    direct = _safe(root / rfilename)
    if direct is not None:
        return direct
    basename = Path(rfilename).name
    for p in root.rglob(basename):
        if any(part.startswith(".") for part in p.relative_to(root).parts):
            continue
        safe = _safe(p)
        if safe is not None:
            return safe
    return None


def _verify_mlx_files(
    target: Path, model_id: str, expected_files: dict[str, str]
) -> bool:
    """Verify each pinned LFS file of an MLX snapshot against its HF sha256.

    Tier-2 (provider-published) MLX pin, ADR B046b. For every published
    ``{rfilename: sha256}`` (the big ``.safetensors`` weights), locate the file
    inside ``target`` and re-hash it. A missing or mismatching pinned weight
    file raises ``DownloadIntegrityError`` (fail-closed); the artefact is
    preserved on disk for post-mortem. ``expected_files`` is non-empty (the
    caller checks), so a True result always means real verification happened.
    """
    for rfilename, expected_sha in expected_files.items():
        located = _locate_in_dir(target, rfilename)
        if located is None:
            msg = (
                f"Pinned MLX weight {rfilename!r} missing from {model_id!r} "
                f"snapshot at {target} — the download is incomplete or tampered.\n"
                f"{_retry_instructions('mlx', model_id, target)}"
            )
            raise DownloadIntegrityError(artifact=model_id, message=msg)
        actual_sha = sha256_of_file(located)
        try:
            verify_sha256(
                actual_sha,
                expected_sha,
                artifact=f"mlx:{model_id}:{rfilename}",
                allow_missing=False,
            )
        except HashMismatchError as exc:
            msg = (
                f"SHA256 mismatch for MLX weight {rfilename!r} of {model_id!r}.\n"
                f"  expected: {exc.expected}\n"
                f"  actual:   {exc.actual}\n"
                f"The downloaded artefact has been preserved at {target} for inspection.\n"
                f"{_retry_instructions('mlx', model_id, target)}"
            )
            raise DownloadIntegrityError(
                artifact=model_id, message=msg, cause=exc
            ) from exc
    return True


# ═══════════════════════════════════════════════════════════════════════
# Public entry point — call this after each download.
# ═══════════════════════════════════════════════════════════════════════


def verify_download_integrity(
    engine: str,
    model_id: str,
    target: Path,
) -> bool:
    """Verify the SHA256 of a freshly downloaded artefact against the catalog.

    Returns
    -------
    bool
        * ``True``  — a pin exists AND the downloaded artefact matches it,
          OR the engine is ``ollama`` (integrity delegated to Ollama's own
          content-addressed pull — see below).
        * ``False`` — the catalog has no pin for this ``(engine, model_id)``.
          The caller has already seen a WARNING in the log and should
          continue with the install while surfacing a "not pinned" notice
          (or asking for explicit consent — ADR B046b).

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

    # Ollama (ADR B251): integrity is delegated to Ollama's own
    # content-addressed pull — the daemon verifies every layer against the
    # manifest digest during `ollama pull` (THREAT_MODEL §4.3). We keep no
    # redundant client-side pin: Ollama catalog tags are mutable upstream, so
    # a pinned digest would raise a false DownloadIntegrityError every time
    # the provider re-publishes a tag. Short-circuit to a logged True.
    if engine == "ollama":
        logger.info(
            "Integrity: ollama %r verified by Ollama's content-addressed pull "
            "(no client-side pin; tags are mutable upstream).", model_id,
        )
        return True

    # Tier-2 MLX (ADR B046b): no self-computed dir-hash, but Hugging Face
    # publishes per-LFS-file sha256. Verify each weight file individually.
    # Tier-1 dir-hash (when present) is stronger and wins via the path below.
    if engine == "mlx" and get_expected_sha256(engine, model_id) is None:
        mlx_files = get_expected_mlx_file_hashes(model_id)
        if mlx_files:
            return _verify_mlx_files(target, model_id, mlx_files)
        # No tier-1 and no tier-2 → genuinely unpinned: fall through to the
        # generic path, which returns False (allow_missing) → consent gate.

    expected = get_expected_sha256(engine, model_id)
    actual = _compute_actual(engine, target)
    if actual is None:
        # Could not determine the actual digest. Treat as legacy; the user
        # sees a warning already.
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
        * ``False`` — bundle missing, manifest absent (legacy DMG) or
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
            "legacy DMG. Proceeding without SHA256 enforcement.",
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
    "verify_download_integrity",
    "verify_embedding_bundle",
]
