"""Centralized resolver for the default Qdrant/vectors path.

In sidecar mode (`NEXE_SIDECAR=1`) returns `SidecarConfig.vectors_dir`
(propagates `NEXE_QDRANT_PATH` injected by Tauri). In standalone mode
returns `NEXE_QDRANT_PATH` anchored at the repo root when set (#1053), else
the caller's default or the legacy literal `storage/vectors` (relative to cwd).

Light-touch defensive: any failure resolving SidecarConfig falls back to
the legacy default with `logger.debug` (no silent `pass`).

Used by:
- `memory.memory.api.MemoryAPI`
- `memory.memory.engines.persistence.PersistenceManager`
- `memory.memory.storage.vector_index.VectorIndex`
- `memory.memory.memory_service.MemoryService`
- `memory.memory.config.MemoryConfig.qdrant_path` (consumers default)

Anomalia F1 A5 ("NEXE_QDRANT_PATH no respectat") resolta completament
quan tots els mòduls memory/ adopten aquest helper.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Union

logger = logging.getLogger(__name__)

_LEGACY_DEFAULT = Path("storage/vectors")


def resolve_qdrant_path(
    default: Union[Path, str, None] = None, *, root: Union[Path, str, None] = None,
) -> Path:
    """Returns `SidecarConfig.vectors_dir` in sidecar mode, otherwise `default`.

    Args:
        default: Fallback path when not in sidecar mode or when SidecarConfig
            is unavailable. If None, uses `storage/vectors` (legacy hardcoded
            default per F8 fix at lifespan_modules.py:295).
        root: The project root the caller works under. An absolute
            NEXE_QDRANT_PATH always wins; a relative one is anchored at `root`,
            or at the repo root when the caller gave neither root nor default.

    Returns:
        Path: resolved Qdrant storage path.
    """
    try:
        from core.sidecar_config import get_sidecar_config

        cfg = get_sidecar_config()
        if cfg.is_sidecar:
            return cfg.vectors_dir
    except Exception as exc:  # pragma: no cover — fallback when SidecarConfig unavailable
        logger.debug(
            "SidecarConfig unavailable, using legacy default %r: %s",
            default if default is not None else _LEGACY_DEFAULT,
            exc,
        )

    # Standalone honours NEXE_QDRANT_PATH too (#1053): the core's Qdrant
    # followed the variable and memory did not, so a live run "isolated" by it
    # still wrote facts into the DEV store (seen 25/09). Relative means "under
    # the project the caller runs": the DEV .env says `storage/vectors`, and
    # core/server/runner.py loads that .env into every process that imports it.
    if env_path := os.environ.get("NEXE_QDRANT_PATH", "").strip():
        p = Path(env_path).expanduser()
        if p.is_absolute():
            return p
        if root is not None:
            return Path(root) / p
        if default is None:
            from core.qdrant_pool import _anchor_path
            return _anchor_path(env_path)
        # A caller with its own default and no root keeps it: a relative value
        # names the default layout, and anchoring it at the repo would pull a
        # caller looking at another storage dir onto the repo's.

    if default is None:
        return _LEGACY_DEFAULT
    return Path(default) if isinstance(default, str) else default
