#!/usr/bin/env python3
"""
provider_hashes.py — fetch provider-published checksums (metadata only).

ADR B046b (provider-published weight pinning). Instead of hard-coding a
self-computed pin for every model — which would mean downloading every MLX
snapshot once — we pin against the checksums the upstream provider already
publishes, read over the metadata APIs WITHOUT downloading any model bytes:

  * Hugging Face — each LFS file (the big ``.safetensors`` / ``.gguf`` weights,
    i.e. the integrity-critical artefacts) carries an ``lfs.sha256`` digest in
    ``HfApi().model_info(repo, files_metadata=True)``. Small non-LFS files
    (config.json, tokenizer*) are git-blob (sha1), not sha256, and are out of
    scope of this pin (documented in THREAT_MODEL).

Ollama is NOT covered here (ADR B251): its content-addressed pull verifies
layer integrity on its own, and its tags are mutable upstream, so we keep no
client-side Ollama pin.

This module is used by ``installer/bootstrap_catalog_pins.py`` to populate
``installer/provider_pins.json``; it is NOT on the user's install hot-path (the
pins are already in the catalog by then). Every failure mode logs a WARNING and
returns an empty / ``None`` result so the bootstrap can skip a model rather
than crash — a missing pin degrades to the explicit-consent path, never to a
silent fail-open.

Threat-model caveat: a provider-published pin defends against MITM / in-transit
corruption, NOT against a compromised provider repo (which would serve bad
bytes and a matching bad checksum). See ADR B046b.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# Hugging Face — per-file LFS sha256 (metadata only, no download)
# ═══════════════════════════════════════════════════════════════════════
def fetch_hf_lfs_hashes(repo_id: str, *, revision: str = "main") -> dict[str, str]:
    """Return ``{rfilename: sha256}`` for every LFS file in ``repo_id``.

    Reads ``HfApi().model_info(repo_id, files_metadata=True)`` — no model
    bytes are downloaded. Non-LFS files (``lfs is None``) are skipped: their
    blob id is a git sha1, not the content sha256 we verify against.

    On any error (network, repo not found, HF rate-limit) logs a WARNING and
    returns ``{}`` so the caller treats the model as "not yet pinned".
    """
    try:
        # Imported lazily: huggingface_hub is a heavy transitive dep and this
        # module is also imported by lightweight catalog tooling.
        from huggingface_hub import HfApi

        info = HfApi().model_info(repo_id, revision=revision, files_metadata=True)
    except Exception as exc:  # noqa: BLE001 — any failure → skip, never crash
        logger.warning(
            "provider_hashes: could not fetch HF metadata for %r (%s): %s",
            repo_id, revision, exc,
        )
        return {}

    hashes: dict[str, str] = {}
    for sibling in info.siblings or []:
        lfs = getattr(sibling, "lfs", None)
        sha = getattr(lfs, "sha256", None) if lfs is not None else None
        if sha:
            hashes[sibling.rfilename] = sha
    if not hashes:
        logger.warning(
            "provider_hashes: HF repo %r exposed no LFS sha256 (no weights to "
            "pin via metadata) — model stays unpinned", repo_id,
        )
    return hashes
