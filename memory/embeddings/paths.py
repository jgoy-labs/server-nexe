"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: memory/embeddings/paths.py
Description: Filesystem paths shared by the embedding subsystem and the installer.

This is the SINGLE SOURCE OF TRUTH for the fastembed cache directory.

Why this exists:
  fastembed's TextEmbedding(model_name) defaults its cache to
  `tempfile.gettempdir() / "fastembed_cache"`. On macOS that resolves to
  /var/folders/<id>/T/fastembed_cache/ which is automatically purged by
  the OS (typically every few days, or when free space is reclaimed).
  Meanwhile the DMG installer copies the bundled int8 ONNX model to
  ~/.cache/fastembed/ — the cross-platform fastembed convention. The
  two paths disagree, so RAG silently breaks the first time macOS purges
  the temporary directory even though the model is still on disk.

Contract:
  All call-sites that instantiate `TextEmbedding(model_name)` MUST pass
  `cache_dir=str(default_fastembed_cache_dir())` so runtime and installer
  agree on a single persistent location, both in dev and in DMG production.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from __future__ import annotations

import os
from pathlib import Path


def default_fastembed_cache_dir() -> Path:
    """Return the canonical fastembed cache directory for the current user.

    Resolution order:
      1. ``FASTEMBED_CACHE_DIR`` env var (override — used by the dev wizard,
         tests, or operators redirecting the cache to an alternative disk).
      2. ``~/.cache/fastembed/`` — the cross-platform fastembed convention,
         and the location the DMG installer seeds via ``_seed_fastembed_cache``.

    Returns
    -------
    Path
        Absolute, expanded path. Caller is responsible for ``mkdir`` if
        the directory must exist before use; ``TextEmbedding`` itself
        creates the directory on first download.
    """
    env_override = os.environ.get("FASTEMBED_CACHE_DIR")
    if env_override:
        return Path(env_override).expanduser()
    return Path.home() / ".cache" / "fastembed"


__all__ = ["default_fastembed_cache_dir"]
