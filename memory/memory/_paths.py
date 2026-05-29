"""Centralized resolver for the default Qdrant/vectors path.

In sidecar mode (`NEXE_SIDECAR=1`) returns `SidecarConfig.vectors_dir`
(propagates `NEXE_QDRANT_PATH` injected by Tauri). In standalone mode
returns the legacy literal `storage/vectors` (relative to cwd).

Light-touch defensive: any failure resolving SidecarConfig falls back to
the legacy default with `logger.debug` (no silent `pass`).

Used by:
- `memory.memory.api.MemoryAPI`
- `memory.memory.engines.persistence.PersistenceManager`
- `memory.memory.storage.vector_index.VectorIndex`
- `memory.memory.memory_service.MemoryService`
- `memory.rag.module.get_file_rag`
- `memory.memory.config.MemoryConfig.qdrant_path` (consumers default)

Anomalia F1 A5 ("NEXE_QDRANT_PATH no respectat") resolta completament
quan tots els mòduls memory/ adopten aquest helper.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Union

logger = logging.getLogger(__name__)

_LEGACY_DEFAULT = Path("storage/vectors")


def resolve_qdrant_path(default: Union[Path, str, None] = None) -> Path:
    """Returns `SidecarConfig.vectors_dir` in sidecar mode, otherwise `default`.

    Args:
        default: Fallback path when not in sidecar mode or when SidecarConfig
            is unavailable. If None, uses `storage/vectors` (legacy hardcoded
            default per F8 fix at lifespan_modules.py:295).

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
            "F2.2: SidecarConfig unavailable, using legacy default %r: %s",
            default if default is not None else _LEGACY_DEFAULT,
            exc,
        )

    if default is None:
        return _LEGACY_DEFAULT
    return Path(default) if isinstance(default, str) else default
