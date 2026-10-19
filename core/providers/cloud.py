"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/providers/cloud.py
Description: The gate a turn passes before it may leave this machine.

    Two decisions of Jordi (06/10/2026) live here and nowhere else:

    * a global switch, "Allow cloud engines" (`NEXE_ALLOW_CLOUD_ENGINES`), off
      by default and read fail-closed: only an explicit yes turns it on;
    * a consent PER SESSION at the web door, PER REQUEST at `/v1` (it has no
      session to remember one), for one provider: the conversation, the retrieved
      documents and the memory leave the machine towards that provider, and
      so do the turn's internal steps (memory, compaction, image description),
      which run on the same engine.

    `require_cloud_turn` is door-blind and engine-blind: it answers for a
    model name and two consent values, and raises `CloudRefusal`, which the
    caller turns into its own HTTP answer. It reads no key (only whether one
    exists) and makes no network call.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from .registry import Provider, is_configured, provider_for_model

#: The environment variable (and runtime override) behind the global switch.
ALLOW_CLOUD_ENV = "NEXE_ALLOW_CLOUD_ENGINES"

#: The engine name the selector, the routing tables and the chat body use.
CLOUD_ENGINE = "api"

_TRUE = frozenset({"1", "true", "yes", "on"})


def cloud_engines_allowed() -> bool:
    """True only when the switch was explicitly turned on.

    Anything else — unset, empty, "0", a typo — is off: the failure of this
    read must keep the machine closed, not open.
    """
    from core.runtime_state import get_with_env_fallback

    return str(get_with_env_fallback(ALLOW_CLOUD_ENV, "") or "").strip().lower() in _TRUE


class CloudRefusal(Exception):
    """A turn that may not go to a provider, and why.

    `code` is stable (the UI reads it), `status` is the HTTP answer. The text
    is curated: it names the provider and the setting, never a key.
    """

    def __init__(self, status: int, code: str, message: str, provider: Optional[Provider] = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.provider = provider

    def detail(self) -> Dict[str, Any]:
        """The body the client gets: enough for the UI to ask for consent."""
        out: Dict[str, Any] = {"code": self.code, "message": self.message}
        if self.provider is not None:
            out["provider"] = self.provider.key
            out["provider_name"] = self.provider.name
        return out


def require_cloud_selection(model: Optional[str]) -> Provider:
    """The provider `model` would go to, if this server may use it at all.

    The part of the gate that does not need the session: picking an API model
    in the selector is refused while the switch is off, for a model no
    provider owns, and for a provider with no key. Order matters: the switch
    first (nothing else is said while it is off), then the model (the request
    names no provider), then the key.
    """
    if not cloud_engines_allowed():
        raise CloudRefusal(
            403, "cloud_engines_disabled",
            "Cloud engines are turned off. Turn on \"Allow cloud engines\" to use an API provider.",
        )
    provider = provider_for_model(model)
    if provider is None:
        raise CloudRefusal(400, "cloud_model_not_allowed", "That model does not belong to any configured API provider.")
    if not is_configured(provider):
        raise CloudRefusal(
            400, "cloud_provider_not_configured",
            f"{provider.name} has no key configured on this server.", provider,
        )
    return provider


def require_cloud_turn(
    model: Optional[str], *, requested_consent: Optional[str], session_consent: Optional[str],
) -> Provider:
    """The provider this turn would go to, or `CloudRefusal`.

    The selection checks, then the consent. Consent is for one provider by
    key: a session that agreed to DeepSeek has not agreed to OpenAI.
    """
    provider = require_cloud_selection(model)
    if provider.key not in (requested_consent, session_consent):
        raise CloudRefusal(
            403, "cloud_consent_required",
            f"This conversation, its documents and its memory would leave this machine for {provider.name}. "
            "Consent is required for this session.", provider,
        )
    return provider


def require_cloud_request(model: Optional[str], consent: Optional[str]) -> Provider:
    """The provider a stateless request (`/v1`) would go to, or `CloudRefusal`.

    The door with no session and no dialog: the consent is the request's own,
    named in its body, for ONE provider by key, and it counts for that request
    only. Nothing is remembered, so the next request must say it again — the
    same switch, model and key checks as a web turn, with no session consent
    to fall back on.
    """
    return require_cloud_turn(model, requested_consent=consent, session_consent=None)
