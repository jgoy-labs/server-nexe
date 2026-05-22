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
