"""
F5.3.1: Persistent onboarding state.

The wizard writes the user's engine + model selection to a JSON file. The
sidecar reads it at startup and configures env vars accordingly. This is the
single source of truth — no other layer holds onboarding state.

Location: $NEXE_DATA_DIR/onboarding.json (sidecar mode injects NEXE_DATA_DIR)
Fallback (no NEXE_DATA_DIR):
  - macOS:   ~/Library/Application Support/com.nexe.app/sidecar/onboarding.json
             (legacy literal preserved for backward compat with v0.9 Macs)
  - Linux:   platformdirs.user_data_dir("nexe-app", "nexe")/sidecar/onboarding.json
             ($XDG_DATA_HOME or ~/.local/share/nexe-app/sidecar/onboarding.json)

Schema versioned. Writes are atomic (tmp + rename within same directory).

F5.4 Fase 4b — optional Hugging Face token persisted to the macOS Keychain
via the ``keyring`` package (Turing #2 C5: service name "nexe-hf-token" to
avoid iCloud-keychain sync with com.nexe.app personal keychain entries).
The token itself NEVER hits disk; only a boolean marker ``has_token`` is
written to onboarding.json so the next sidecar restart knows to attempt
keyring lookup at startup.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import platformdirs

from core.installer_constants import VALID_ENGINES as _VALID_ENGINES

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 2  # F5.4 Fase 4b: added has_token field. Older v1 files
                    # are still readable (has_token defaults to False) but we
                    # bump the schema so a backwards-incompatible field could
                    # be added without silently misreading older state.

# Turing #2 C5: use a dedicated keyring service (not "com.nexe.app") to
# avoid the macOS Keychain potentially sharing the entry with other apps
# that also identify as com.nexe.app, and to opt out of iCloud Keychain
# sync (which can mirror application-keychain entries across devices).
_KEYCHAIN_SERVICE = "nexe-hf-token"
_KEYCHAIN_USER = "default"
_HF_TOKEN_ENV_VAR = "HF_TOKEN"  # nosec B105 — env var name, not a password literal

# Mapping from the wizard's engine identifier to the key accepted by
# `_resolve_engines` in plugins/web_ui_module/api/routes_chat.py.
# Discovered empirically — the routes_chat resolver uses "mlx" / "ollama" /
# "llamacpp" / "auto", not module suffixes like "mlx_module".
_ENGINE_TO_RESOLVER_KEY: dict[str, str] = {
    "mlx": "mlx",
    "ollama": "ollama",
    "gguf": "llamacpp",
}

# Mapping from the wizard's engine identifier to the env var that the
# corresponding plugin reads to pick its model path.
_ENGINE_TO_MODEL_ENV: dict[str, str] = {
    "mlx": "NEXE_MLX_MODEL",
    "gguf": "NEXE_LLAMA_CPP_MODEL",
    # ollama uses model_id (not a path) so no env var is set.
}


@dataclass(frozen=True)
class OnboardingState:
    """Immutable record of the user's onboarding choices."""

    version: int
    engine: str  # "mlx" | "ollama" | "gguf"
    model_id: str  # e.g. "mlx-community/gemma-3-4b-it-4bit" or "gemma3:4b"
    model_path: str  # absolute path to local model dir/file (or model_id for ollama)
    completed_at: str  # ISO 8601 UTC
    # F5.4 Fase 4b: marker for Hugging Face token presence. The token itself
    # is stored in the Keychain (service=_KEYCHAIN_SERVICE). Default False
    # for v1-schema files which lacked this field.
    has_token: bool = False
    # 2026-05-22: BCP-47 language code selected at the wizard welcome step
    # (Català/Español/English). Persisted so the sidecar can render the UI
    # in the chosen language at the next startup (read by
    # plugins.web_ui_module.api.routes_auth.get_server_lang). Default "en"
    # for files written by older versions of the wizard that lacked this
    # field — neutral OSS default, browser fallback still applies if the
    # field is missing in the loaded JSON.
    lang: str = "en"

    @staticmethod
    def _state_file() -> Path:
        """Return the canonical path to onboarding.json.

        Linux portability (factoria-linux-bus 2026-05-22): the original
        default was the Mac-only literal
        ``~/Library/Application Support/com.nexe.app/sidecar/onboarding.json``
        with no platform gate, which on Linux produced an out-of-place
        ``~/Library/...`` tree. We now branch on ``platform.system()``:
          - macOS  → original literal preserved (zero risk for existing Mac
                     installs — same path, same file).
          - Linux  → ``platformdirs.user_data_dir("nexe-app", "nexe")`` =
                     ``$XDG_DATA_HOME`` or ``~/.local/share/nexe-app``.
          - other  → falls back to platformdirs for sanity.
        ``NEXE_DATA_DIR`` still wins over the default (sidecar bundle mode).
        """
        import platform as _platform
        data_dir = os.environ.get("NEXE_DATA_DIR")
        if data_dir:
            return Path(data_dir).expanduser() / "onboarding.json"
        if _platform.system() == "Darwin":
            # Preserved literal — DO NOT change without a migration story
            # for existing Mac installs that already have onboarding.json
            # at this exact path.
            return (
                Path.home()
                / "Library"
                / "Application Support"
                / "com.nexe.app"
                / "sidecar"
                / "onboarding.json"
            )
        return (
            Path(platformdirs.user_data_dir("nexe-app", "nexe"))
            / "sidecar"
            / "onboarding.json"
        )

    @classmethod
    def load(cls) -> OnboardingState | None:
        """Return the persisted state, or None if not completed / unreadable."""
        path = cls._state_file()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("onboarding_state: failed to load: %s", exc)
            return None
        # F5.4 Fase 4b: forward-compat with v1 schema (pre-has_token). v1
        # files lack the has_token field; promote them to v2 by injecting
        # the default False so a user who completed onboarding before the
        # token field existed doesn't have to redo the wizard.
        raw_version = raw.get("version")
        if raw_version == 1:
            raw["version"] = SCHEMA_VERSION
            raw.setdefault("has_token", False)
        elif raw_version != SCHEMA_VERSION:
            logger.warning(
                "onboarding_state: schema mismatch (got %s expected %s)",
                raw_version, SCHEMA_VERSION,
            )
            return None
        # 2026-05-22: forward-compat for the lang field. v2 files written
        # before this commit lack it; promote with neutral "en" default so
        # they still load without re-running the wizard. The dataclass
        # default would handle missing keyword args but only if we strip
        # them from the dict — we keep the dict-rebuild pattern explicit.
        raw.setdefault("lang", "en")
        try:
            return cls(**raw)
        except TypeError as exc:
            logger.warning("onboarding_state: malformed payload: %s", exc)
            return None

    # Sentinel: distinguish "caller did not pass hf_token" (preserve existing
    # has_token flag) from "caller passed hf_token=None" (explicitly clear).
    # Turing #3 P4: without this, a re-run of the wizard without a token
    # would silently flip has_token from True to False, breaking the next
    # apply_to_env. Use a unique object so None remains a valid "clear" value.
    _UNSET = object()

    @classmethod
    def save(
        cls,
        *,
        engine: str,
        model_id: str,
        model_path: str,
        hf_token: Optional[str] = _UNSET,  # type: ignore[assignment]
        lang: Optional[str] = None,
    ) -> OnboardingState:
        """Atomically persist a new state. Returns the saved instance.

        F5.4 Fase 4b: when ``hf_token`` is provided (non-empty string), it is
        stored to the macOS Keychain via ``keyring`` (service
        ``nexe-hf-token``) and ``has_token`` is set to True in the JSON
        marker. The token itself is NEVER written to disk. If the keyring
        write fails, the token is dropped (a warning is logged) and
        ``has_token`` stays False — the safety net at startup will then
        fall back to operating without a token.

        Turing #3 P4: ``hf_token`` defaults to a sentinel so callers that
        do NOT touch the token preserve the existing ``has_token`` flag
        (read from the previous state file). Passing ``hf_token=None``
        explicitly is treated as "clear the token" (deletes keychain
        entry, sets has_token=False).
        """
        if engine not in _VALID_ENGINES:
            raise ValueError(f"invalid engine: {engine!r}")

        # Resolve has_token according to the sentinel semantics.
        if hf_token is cls._UNSET:
            # Preserve the previous has_token flag if a prior state exists.
            previous = cls.load()
            has_token = previous.has_token if previous is not None else False
        elif hf_token is None:
            # Explicit clear: delete the keychain entry and mark has_token=False.
            clear_hf_token_from_keychain()
            has_token = False
        elif not hf_token:
            # Empty string treated like the sentinel (caller passed "" which
            # is a wizard form artefact, not a deliberate clear). Preserve.
            previous = cls.load()
            has_token = previous.has_token if previous is not None else False
        else:
            # Non-empty token: attempt keyring write.
            has_token = _store_hf_token_in_keychain(hf_token)
        # Lang resolution: caller-provided lang wins; otherwise preserve the
        # previous state's lang (if any); else fall back to "en". Validation
        # is a simple allowlist — anything else falls back to "en" so a
        # malformed wizard payload cannot break the next sidecar startup.
        _valid_langs = {"ca", "es", "en"}
        if lang and lang in _valid_langs:
            resolved_lang = lang
        else:
            previous_lang = cls.load()
            resolved_lang = previous_lang.lang if previous_lang is not None else "en"
            if resolved_lang not in _valid_langs:
                resolved_lang = "en"
        state = cls(
            version=SCHEMA_VERSION,
            engine=engine,
            model_id=model_id,
            model_path=str(Path(model_path).expanduser().resolve()),
            completed_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            has_token=has_token,
            lang=resolved_lang,
        )
        path = cls._state_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        # Atomic write: write to a tmp file in the SAME directory, then rename.
        # Cross-device rename would fail; same-dir guarantees atomicity on POSIX.
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=".onboarding.",
            suffix=".tmp",
            delete=False,
        ) as fh:
            json.dump(asdict(state), fh, indent=2)
            # fsync before rename so a crash mid-finalize cannot produce a
            # zero-byte onboarding.json that would later be parsed as
            # "completed" but fail to apply_to_env at startup.
            fh.flush()
            os.fsync(fh.fileno())
            tmp_path = Path(fh.name)
        os.replace(tmp_path, path)
        logger.info(  # nosemgrep: python-logger-credential-disclosure — has_token is a boolean flag, not a token value
            "onboarding_state: saved (engine=%s model=%s has_token=%s lang=%s)",
            engine, model_id, has_token, resolved_lang,
        )
        return state

    @classmethod
    def is_completed(cls) -> bool:
        """Return True iff a valid state file exists on disk."""
        return cls.load() is not None

    def apply_to_env(self) -> None:
        """Inject this state as env vars for plugin initialization.

        Called by `core.lifespan._startup_init` at startup BEFORE plugins are
        initialized, so MLXConfig / LlamaCppConfig / routes_chat read the
        correct model and engine.

        Env vars set:
          - NEXE_MLX_MODEL or NEXE_LLAMA_CPP_MODEL (path) — engine-specific
          - NEXE_DEFAULT_MODEL (model id) — read by routes_chat default
          - NEXE_MODEL_ENGINE (resolver key) — read by routes_chat to pick engine
          - HF_TOKEN — F5.4 Fase 4b, only when has_token=True and the Keychain
            lookup succeeds. Failure falls back silently (HF Hub still works,
            just rate-limited).
        """
        env_var = _ENGINE_TO_MODEL_ENV.get(self.engine)
        if env_var:
            os.environ[env_var] = self.model_path
        os.environ["NEXE_DEFAULT_MODEL"] = self.model_id
        os.environ["NEXE_MODEL_ENGINE"] = _ENGINE_TO_RESOLVER_KEY[self.engine]
        os.environ["NEXE_LANG"] = self.lang
        # F5.4 Fase 4b: inject HF_TOKEN from Keychain if the user provided
        # one through the wizard. We never log the token value.
        if self.has_token:
            token = _read_hf_token_from_keychain()
            if token:
                os.environ[_HF_TOKEN_ENV_VAR] = token
                logger.info("onboarding_state: HF_TOKEN restored from Keychain")
            else:
                logger.warning(
                    "onboarding_state: has_token=True but Keychain lookup "
                    "returned no token (entry deleted? keyring backend "
                    "unavailable?) — HF Hub will be used unauthenticated."
                )


# ──────────────────────────────────────────────────────────────────────────────
# F5.4 Fase 4b — Keychain helpers (kept at module scope so save/apply share)
# ──────────────────────────────────────────────────────────────────────────────


def _store_hf_token_in_keychain(token: str) -> bool:
    """Persist the HF token to the macOS Keychain. Returns True on success.

    On failure (keyring not installed, backend unavailable, sandbox restriction,
    user denial of keychain access prompt) the caller falls back to operating
    without a token — the wizard does not block on this.
    """
    try:
        import keyring  # type: ignore[import]
    except ImportError:
        logger.warning(
            "onboarding_state: keyring package unavailable — HF token will "
            "NOT be persisted across restarts. Install `keyring` to enable."
        )
        return False
    try:
        keyring.set_password(_KEYCHAIN_SERVICE, _KEYCHAIN_USER, token)
        return True
    except Exception as exc:  # noqa: BLE001
        # Token value MUST NOT appear in the log; only the exception.
        logger.warning("onboarding_state: keyring write failed: %s", exc)
        return False


def _read_hf_token_from_keychain() -> Optional[str]:
    """Look up the HF token from the macOS Keychain. Returns None on miss
    or on any keyring error (graceful: user can still use HF Hub
    unauthenticated, just rate-limited)."""
    try:
        import keyring  # type: ignore[import]
    except ImportError:
        return None
    try:
        return keyring.get_password(_KEYCHAIN_SERVICE, _KEYCHAIN_USER)
    except Exception as exc:  # noqa: BLE001
        logger.warning("onboarding_state: keyring read failed: %s", exc)
        return None


def clear_hf_token_from_keychain() -> bool:
    """Best-effort removal of the HF token from the Keychain. Returns True
    on success. Used by future "Disconnect HF" UI affordances."""
    try:
        import keyring  # type: ignore[import]
    except ImportError:
        return False
    try:
        keyring.delete_password(_KEYCHAIN_SERVICE, _KEYCHAIN_USER)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("onboarding_state: keyring delete failed: %s", exc)
        return False
