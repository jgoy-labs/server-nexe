"""
────────────────────────────────────
Server Nexe
Version: 0.8
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
    """Background task to save conversation data to RAG-searchable memory."""
    try:
        from memory.memory.api.v1 import get_memory_api

        # Create conversation text
        conversation_text = f"User: {user_msg}\nAssistant: {assistant_msg}"

        logger.info("Auto-saving conversation to RAG memory (nexe_chat_memory)...")

        # Use MemoryAPI to store in Qdrant HTTP (same place RAG searches)
        memory = await get_memory_api()

        # Ensure collection exists (idempotent to handle concurrent requests)
        try:
            if not await memory.collection_exists("nexe_chat_memory"):
                await memory.create_collection("nexe_chat_memory", vector_size=DEFAULT_VECTOR_SIZE)
                logger.info("Created nexe_chat_memory collection")
        except Exception:
            # Collection may have been created by concurrent request — verify it exists
            if not await memory.collection_exists("nexe_chat_memory"):
                raise

        # Store the conversation
        doc_id = await memory.store(
            text=conversation_text,
            collection="nexe_chat_memory",
            metadata={
                "type": "conversation_turn",
                "auto_saved": True,
                "source": "chat_interaction",
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        )

        logger.info("Conversation saved to nexe_chat_memory (id=%s)", doc_id)

        try:
            from core.metrics.registry import MEMORY_OPERATIONS
            MEMORY_OPERATIONS.labels(operation="autosave").inc()
        except Exception as e:
            logger.debug("Autosave metrics update failed: %s", e)

    except Exception as e:
        logger.error("Error saving conversation to memory: %s", e)
