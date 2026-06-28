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

# Engines accepted by the onboarding download/preflight endpoints. Adds
# ``"local"`` — the user pointed the wizard at a local models folder (no fixed
# model; the chat UI selector picks one at runtime). ``"local"`` is
# intentionally NOT in ``VALID_ENGINES`` because it is not a downloadable
# engine (the download + preflight endpoints must keep rejecting it).
ONBOARDING_ENGINES: frozenset[str] = VALID_ENGINES | frozenset({"local"})

# Engines that may be the PERSISTED ``engine`` field of ``OnboardingState``.
# This is the resolver's domain: every value here must be handled by
# ``OnboardingState.apply_to_env`` (``"local"`` short-circuits;
# ``mlx``/``ollama``/``gguf`` map through ``_ENGINE_TO_RESOLVER_KEY``).
# ``"embedder"`` is EXCLUDED on purpose — it is a download-only auxiliary
# engine that never becomes the persisted state (MC-022/MC-043: keeping it in
# the persistable set let a poisoned state crash startup with a KeyError).
# Single source of truth: HTTP FinalizeBody.engine, save() validation and
# apply_to_env() must all agree on exactly this set.
PERSISTABLE_ENGINES: frozenset[str] = ONBOARDING_ENGINES - frozenset({"embedder"})
