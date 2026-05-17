"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/lifespan_qdrant.py
Description: Qdrant singleton pool startup/shutdown helpers extracted from lifespan.py.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import logging
import os

logger = logging.getLogger(__name__)


def _startup_qdrant() -> None:
    """Initialize the Qdrant singleton pool.

    F2.1 Sessió 3: in sidecar mode, paths come from SidecarConfig
    (NEXE_QDRANT_PATH respected explicitly) — resolves anomaly A5
    "NEXE_QDRANT_PATH not respected" from F1-smoke/resultats.md.
    """
    from core.qdrant_pool import get_qdrant_client
    qdrant_url = os.environ.get("NEXE_QDRANT_URL")
    qdrant_path: str
    try:
        from core.sidecar_config import get_sidecar_config
        sidecar_cfg = get_sidecar_config()
        # Prefer SidecarConfig values (NEXE_QDRANT_URL / NEXE_QDRANT_PATH parsed).
        if sidecar_cfg.qdrant_url:
            qdrant_url = sidecar_cfg.qdrant_url
        qdrant_path = str(sidecar_cfg.vectors_dir)
    except Exception:  # pragma: no cover — fallback al comportament pre-F2.1
        qdrant_path = os.environ.get("NEXE_QDRANT_PATH", "storage/vectors")
    get_qdrant_client(url=qdrant_url, path=qdrant_path if not qdrant_url else None)


def _shutdown_qdrant() -> None:
    """Close the Qdrant singleton pool."""
    try:
        from core.qdrant_pool import close_qdrant_client
        close_qdrant_client()
        logger.info("Qdrant pool closed")
    except Exception as e:
        logger.debug("Qdrant pool close failed: %s", e)
