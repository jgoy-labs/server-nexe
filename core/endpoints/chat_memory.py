"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/endpoints/chat_memory.py
Description: Conversation memory persistence for Chat endpoint.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import logging
from datetime import datetime, timezone

from memory.memory.constants import DEFAULT_VECTOR_SIZE

logger = logging.getLogger(__name__)

# Tracked background save tasks — prevents "Task was destroyed" warnings on shutdown
_pending_save_tasks: set = set()


async def _save_conversation_to_memory(app_state, user_msg: str, assistant_msg: str):
    """Background task to save conversation data to memory via MemoryService or Qdrant."""
    try:
        conversation_text = f"User: {user_msg}\nAssistant: {assistant_msg}"

        # Try MemoryService first (v1 pipeline)
        try:
            from memory.memory.module import get_memory_service
            svc = get_memory_service()
            if svc and svc.initialized:
                entry_id = await svc.remember(
                    user_id="default",
                    text=conversation_text,
                    source="chat_interaction",
                    trust_level="untrusted",
                )
                if entry_id:
                    logger.info("Conversation saved via MemoryService (id=%s)", entry_id)
                try:
                    from core.metrics.registry import MEMORY_OPERATIONS
                    MEMORY_OPERATIONS.labels(operation="autosave").inc()
                except Exception:
                    pass
                return
        except ImportError:
            pass

        # Legacy Qdrant path
        from memory.memory.api.v1 import get_memory_api

        logger.info("Auto-saving conversation to RAG memory (personal_memory)...")

        memory = await get_memory_api()

        try:
            if not await memory.collection_exists("personal_memory"):
                await memory.create_collection("personal_memory", vector_size=DEFAULT_VECTOR_SIZE)
                logger.info("Created personal_memory collection")
        except Exception:
            if not await memory.collection_exists("personal_memory"):
                raise

        doc_id = await memory.store(
            text=conversation_text,
            collection="personal_memory",
            metadata={
                "type": "conversation_turn",
                "auto_saved": True,
                "source": "chat_interaction",
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        )

        logger.info("Conversation saved to personal_memory (id=%s)", doc_id)

        try:
            from core.metrics.registry import MEMORY_OPERATIONS
            MEMORY_OPERATIONS.labels(operation="autosave").inc()
        except Exception as e:
            logger.debug("Autosave metrics update failed: %s", e)

    except Exception as e:
        logger.error("Error saving conversation to memory: %s", e)
