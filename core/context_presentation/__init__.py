"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/context_presentation/__init__.py
Description: How retrieved context presents itself — the port, the default and
             the resolver the turn asks through.

ADR-008's other half: retrieval got `core/rag/`, presentation gets this. Kept
apart from `core/rag/` on purpose — the attached document is not a RAG source,
and folding the two back together is exactly what that ADR separated.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from core.context_presentation.attach import attach_context_presenter, frame_for
from core.context_presentation.default import DefaultContextPresenter
from core.context_presentation.port import (
    ContextFraming,
    ContextPresenter,
    ContextShape,
)

__all__ = [
    "ContextFraming",
    "ContextPresenter",
    "ContextShape",
    "DefaultContextPresenter",
    "attach_context_presenter",
    "frame_for",
]
