"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/providers/registry.py
Description: Declarative registry of external API providers (DeepSeek,
    OpenAI, ...). An entry only says WHERE the key lives (the name of the
    environment variable) — never its value, not even truncated. Adding a
    provider is adding one entry to PROVIDERS.

    Phase 1: configuration + connection test. Phase 2 reads the same entries
    to chat (`plugins/api_module`) and to build the selector: the chat path,
    the models the selector offers, which of them can see an image, and each
    model's context window are declared here, per entry, never guessed from
    a name elsewhere. Nothing here puts a provider in the engine cascade.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple


@dataclass(frozen=True)
class Provider:
    """Static description of an external provider. Holds no secret."""

    key: str
    name: str
    endpoint: str
    env_var: str
    models: Tuple[str, ...]
    models_path: str = "/v1/models"
    #: Declared, not guessed: whether the `/v1` prefix is part of the path
    #: depends on the provider, so each entry says where it chats.
    chat_path: str = "/v1/chat/completions"
    #: What the selector lists. `models` may hold glob patterns (the allowlist
    #: a request is checked against); a pattern cannot be shown in a dropdown.
    suggested_models: Tuple[str, ...] = ()
    #: Glob patterns of the models that accept an image.
    vision_models: Tuple[str, ...] = ()
    #: Tokens one prompt may hold, by default and per model pattern (first
    #: match wins). Conservative on purpose: a smaller number only makes the
    #: turn's budget smaller.
    context_window: int = 32768
    model_windows: Tuple[Tuple[str, int], ...] = ()
    #: Fixed headers the provider demands besides the key (never a secret).
    #: Anthropic's listing answers 400 without `anthropic-version`.
    extra_headers: Tuple[Tuple[str, str], ...] = ()


PROVIDERS: Tuple[Provider, ...] = (
    Provider(
        key="deepseek",
        name="DeepSeek",
        endpoint="https://api.deepseek.com",
        env_var="DEEPSEEK_API_KEY",
        models=("deepseek-chat", "deepseek-reasoner"),
        suggested_models=("deepseek-chat", "deepseek-reasoner"),
        context_window=64000,
    ),
    Provider(
        key="openai",
        name="OpenAI",
        endpoint="https://api.openai.com",
        env_var="OPENAI_API_KEY",
        models=("gpt-*",),
        suggested_models=("gpt-4o", "gpt-4o-mini"),
        vision_models=("gpt-4o*", "gpt-4.1*", "gpt-5*"),
        context_window=128000,
    ),
    # Anthropic's OpenAI-compatible surface (same /v1 paths, Bearer key). It is
    # their route for trying the API from OpenAI clients, not their native
    # /v1/messages: no prompt caching, and token counts only as the surface
    # reports them. Chat and listing checked against the real service on 13/10.
    Provider(
        key="anthropic",
        name="Claude",
        endpoint="https://api.anthropic.com",
        env_var="ANTHROPIC_API_KEY",
        models=("claude-*",),
        suggested_models=("claude-sonnet-5-5", "claude-opus-5-5", "claude-haiku-5-5", "claude-fable-5-1"),
        vision_models=("claude-*",),
        context_window=200000,
        extra_headers=(("anthropic-version", "2023-06-01"),),
    ),
)


def get_provider(provider_key: str) -> Optional[Provider]:
    """Return the registry entry for `provider_key`, or None if unknown."""
    for provider in PROVIDERS:
        if provider.key == provider_key:
            return provider
    return None


def provider_for_model(model: Optional[str]) -> Optional[Provider]:
    """The provider whose `models` allowlist names `model`, or None.

    The one place a model name is tied to a provider: the chat request carries
    a model, never a provider key. An unknown or empty name matches nothing.
    """
    if not model or not isinstance(model, str):
        return None
    for provider in PROVIDERS:
        if any(fnmatch.fnmatchcase(model, pattern) for pattern in provider.models):
            return provider
    return None


def model_can_see_images(provider: Provider, model: Optional[str]) -> bool:
    """True when the entry declares `model` as image-capable."""
    if not model:
        return False
    return any(fnmatch.fnmatchcase(model, pattern) for pattern in provider.vision_models)


def model_context_window(provider: Provider, model: Optional[str]) -> int:
    """Tokens `model` holds: its pattern's figure, else the entry's default."""
    if model:
        for pattern, window in provider.model_windows:
            if fnmatch.fnmatchcase(model, pattern):
                return window
    return provider.context_window


def read_api_key(provider: Provider) -> str:
    """Return the key from the environment ("" when absent or blank).

    Internal to the provider code: the callers that need the value are the
    connection test and the API engine (`plugins/api_module`), and each puts it
    in one request header and nowhere else — never in a log, an error, a
    result or a repr.
    """
    return os.environ.get(provider.env_var, "").strip()


def is_configured(provider: Provider) -> bool:
    """True when the key is present. Reports presence only — never the value
    nor its length."""
    return bool(read_api_key(provider))


def provider_status() -> Dict[str, Any]:
    """Per-provider presence, never the key. Makes no network call."""
    return {
        "providers": [
            {
                "key": p.key,
                "name": p.name,
                "endpoint": p.endpoint,
                "env_var": p.env_var,
                "models": list(p.models),
                "configured": is_configured(p),
            }
            for p in PROVIDERS
        ]
    }
