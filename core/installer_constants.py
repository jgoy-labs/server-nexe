"""Shared constants for the installer subsystem.

Single source of truth for engine identifiers used by both
``core.endpoints.installer`` (download + preflight endpoints) and
``core.onboarding_state`` (wizard state persistence).

``"embedder"`` is an auxiliary download engine (fastembed model) that is
always downloaded alongside the primary LLM engine; it never becomes the
persisted ``engine`` field of ``OnboardingState``.
"""
from __future__ import annotations

VALID_ENGINES: frozenset[str] = frozenset({"mlx", "ollama", "gguf", "embedder"})

# Engines accepted as a persisted onboarding state. Adds ``"local"`` — the
# user pointed the wizard at a local models folder (no fixed model; the chat
# UI selector picks one at runtime). ``"local"`` is intentionally NOT in
# ``VALID_ENGINES`` because it is not a downloadable engine (the download +
# preflight endpoints must keep rejecting it).
ONBOARDING_ENGINES: frozenset[str] = VALID_ENGINES | frozenset({"local"})
