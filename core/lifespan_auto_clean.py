"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/lifespan_auto_clean.py
Description: Auto-clean startup helper extracted from lifespan.py.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import logging
import os

from core.env_utils import parse_truthy

logger = logging.getLogger(__name__)


async def _startup_auto_clean(server_state, _translate) -> None:
    """Run auto-clean on startup if NEXE_AUTO_CLEAN_ENABLED is set."""
    auto_clean_enabled = parse_truthy(os.getenv(
        'NEXE_AUTO_CLEAN_ENABLED', os.getenv('AUTO_CLEAN_ENABLED', 'false')
    ))

    if not auto_clean_enabled:
        return

    try:
        from personality.auto_clean.core.auto_clean import run_auto_clean

        msg = _translate(server_state.i18n, "core.server.auto_clean_start",
            "Auto-Clean: Running automatic cleanup...")
        logger.info(msg)

        dry_run = parse_truthy(os.getenv(
            'NEXE_AUTO_CLEAN_DRY_RUN', os.getenv('AUTO_CLEAN_DRY_RUN', 'true')
        ))
        result = await run_auto_clean(
            core_root=server_state.project_root,
            dry_run=dry_run,
        )

        if result.get("files_cleaned", 0) > 0 or result.get("would_clean", 0) > 0:
            action = "would clean" if dry_run else "cleaned"
            count = result.get("would_clean", 0) if dry_run else result.get("files_cleaned", 0)
            msg = _translate(server_state.i18n, "core.server.auto_clean_done",
                "Auto-Clean: {count} files {action}", count=count, action=action)
            logger.info(msg)
        else:
            msg = _translate(server_state.i18n, "core.server.auto_clean_nothing",
                "Auto-Clean: Nothing to clean")
            logger.debug(msg)

    except ImportError:
        logger.debug("Auto-Clean not available")
    except Exception as e:
        msg = _translate(server_state.i18n, "core.server.auto_clean_error",
            "Auto-Clean error: {error}", error=str(e))
        logger.warning(msg)
