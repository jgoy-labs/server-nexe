"""Hugging Face access for the wizard: token, gating and repo identity.

Split out of ``core.endpoints.installer`` (finding #969). Shared by the two
engines that download from the Hub (MLX and GGUF) and by the preflight
endpoint, which is why it is its own module and not part of either engine.

Depends only on ``installer_shared``; it must never import an engine module or
``installer`` itself, or the family grows a cycle.
"""

from __future__ import annotations

import asyncio
import logging
import os
from urllib.parse import urlparse

from core.endpoints import installer_shared
from core.onboarding_state import _read_hf_token_from_keychain

logger = logging.getLogger(__name__)

def _is_hf_hub_url(url: str) -> bool:
    """True iff the URL host is on the HuggingFace Hub.

    Used to decide whether to attach the HF token: we only ever send it to HF
    hosts, never to an arbitrary catalog host. The endswith check is anchored on
    a leading dot so ``huggingface.co.evil.com`` and ``evilhuggingface.co`` do
    not match.
    """
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    return host == "huggingface.co" or host == "hf.co" or host.endswith(".huggingface.co")

def _hf_repo_id_from_url(url: str) -> "str | None":
    """Derive the HF repo_id (org/model) from a Hugging Face Hub file URL.

    GGUF models are referenced by a raw .gguf URL like
    ``https://huggingface.co/<org>/<model>/resolve/<rev>/<file>.gguf``, but the
    HF preflight (model_info / snapshot_download) expects a repo_id. Returns the
    ``<org>/<model>`` segment, or None when the URL is not on the HF Hub or the
    path is too short to carry a repo_id (caller should then skip the HF probe).
    """
    if not _is_hf_hub_url(url):
        return None
    try:
        path = urlparse(url).path.strip("/")
    except ValueError:
        return None
    parts = [p for p in path.split("/") if p]
    # Cut at the first path marker; the repo_id is everything before it.
    for marker in ("resolve", "blob", "tree", "raw"):
        if marker in parts:
            parts = parts[: parts.index(marker)]
            break
    if len(parts) < 2:
        return None
    return "/".join(parts[:2])

def _preflight_repo_id(model_id: str) -> "str | None":
    """Map a preflight model_id to the HF repo_id to probe, or None to skip (B257).

    mlx model_ids are already repo_ids (``org/model``) → returned as-is. gguf
    model_ids are raw HF file URLs → derive the repo_id. A gguf URL on a non-HF
    catalog host has no HF gated/size concept → return None so the caller skips
    the HF probe instead of passing a URL to model_info/snapshot_download (which
    expect a repo_id and would degrade to a spurious network_error/not_found).
    """
    if "://" in model_id:
        return _hf_repo_id_from_url(model_id)
    return model_id

# Timeout for the off-thread Keychain read in _ensure_hf_token_in_env (CRY-01).
# Module-level so tests can shrink it; mirrors the 5s write guard in set_hf_token.
_HF_KEYCHAIN_READ_TIMEOUT = 5.0

async def _ensure_hf_token_in_env() -> str | None:
    """Return the HF token for gated access, restoring it from the Keychain into
    ``os.environ`` if the live env lost it (B253).

    ``set_hf_token`` (step 3) stores the token to the Keychain best-effort, but
    the preflight + ``snapshot_download`` only read ``os.environ['HF_TOKEN']``
    (process-local). If the sidecar PROCESS restarts mid-download (force-quit +
    reopen, or a crash), the env is gone and ``apply_to_env`` cannot help — it is
    only invoked when ``OnboardingState.load()`` succeeds, which does NOT happen
    while the wizard is still mid-flow (the state file is written at finalize,
    step 5). The token then sits orphaned in the Keychain. We read it here and
    re-inject it so the env-based preflight + download pick it up. No-op (zero
    Keychain access) when the env already holds the token — the common case.
    """
    token = os.environ.get("HF_TOKEN") or None
    if token:
        return token
    # Read the Keychain OFF the event loop with a timeout: a headless macOS
    # Keychain ACL prompt can block for minutes when the bundled Python binary is
    # not on the item's ACL (precedent CRY-01 — the same guard B054 applied to
    # the WRITE path in set_hf_token). On timeout/error the wizard keeps going
    # without a token rather than hanging the whole sidecar.
    try:
        loop = asyncio.get_event_loop()
        token = await asyncio.wait_for(
            loop.run_in_executor(installer_shared._dl_executor, _read_hf_token_from_keychain),
            timeout=_HF_KEYCHAIN_READ_TIMEOUT,
        )
    except Exception as exc:  # noqa: BLE001 — timeout or keyring error: never fatal
        logger.warning("installer: Keychain read for HF_TOKEN skipped (%s)", type(exc).__name__)
        token = None
    if token:
        os.environ["HF_TOKEN"] = token
        logger.info("installer: HF_TOKEN restored from Keychain (mid-flow restart recovery, B253)")
    return token

def _check_model_access(repo_id: str, token: str | None = None) -> dict:
    """Inspect a Hugging Face repo to detect gated/private/missing status.

    Returns one of:
      {"status": "ok"}
      {"status": "gated", "url": "https://huggingface.co/<repo_id>"}
      {"status": "gated_no_access", "url": ...}
      {"status": "not_found"}
      {"status": "network_error", "reason": "..."}
    """
    try:
        from huggingface_hub import HfApi
        from huggingface_hub.errors import (
            GatedRepoError,
            RepositoryNotFoundError,
        )
    except ImportError as exc:
        return {"status": "network_error", "reason": f"huggingface_hub missing: {exc}"}

    api = HfApi(token=token) if token else HfApi()
    try:
        info = api.model_info(repo_id, expand=["gated"])
    except GatedRepoError:
        return {
            "status": "gated_no_access",
            "url": f"https://huggingface.co/{repo_id}",
        }
    except RepositoryNotFoundError:
        return {"status": "not_found"}
    except Exception as exc:  # noqa: BLE001  network/timeout/etc.
        return {"status": "network_error", "reason": str(exc)}

    gated = getattr(info, "gated", None)
    if gated in ("auto", "manual"):
        return {
            "status": "gated" if token else "gated_no_access",
            "url": f"https://huggingface.co/{repo_id}",
        }
    return {"status": "ok"}

def _dry_run_plan(repo_id: str, token: str | None = None) -> dict:
    """Probe the snapshot_download plan without downloading any bytes.

    Returns: {"total_bytes": int, "cached_bytes": int, "files_count": int}
    or {"error": "..."} on failure.
    """
    try:
        from huggingface_hub import snapshot_download  # type: ignore[import]
    except ImportError as exc:
        return {"error": f"huggingface_hub missing: {exc}"}
    try:
        plan = snapshot_download(repo_id=repo_id, dry_run=True, token=token)  # nosec B615 — dry_run=True: no download occurs, only metadata; token from Keychain
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}
    total = 0
    cached = 0
    count = 0
    for item in plan:
        size = int(getattr(item, "file_size", 0) or 0)
        total += size
        if getattr(item, "is_cached", False):
            cached += size
        count += 1
    return {
        "total_bytes": total,
        "cached_bytes": cached,
        "files_count": count,
    }

async def _preflight_hf_access(engine: str, model_id: str) -> "dict | None":
    """Pre-flight HuggingFace gated/not-found check for mlx/gguf engines.

    Returns an error event dict if access is denied or model not found, else None.
    Extracted from download_model.generate to reduce CCN.
    """
    if engine not in ("mlx", "gguf"):
        return None
    # gguf model_ids are raw .gguf URLs; HF probes need the repo_id (B257). A
    # gguf URL on a non-HF host has no HF gated concept → fall through to download.
    repo_id = _preflight_repo_id(model_id)
    if repo_id is None:
        return None
    # Falls back to the Keychain (re-injecting into the env) so a token handed
    # over before a mid-flow sidecar restart still authenticates the retry (B253).
    token = await _ensure_hf_token_in_env()
    loop = asyncio.get_event_loop()
    access = await loop.run_in_executor(installer_shared._dl_executor, _check_model_access, repo_id, token)
    status = access.get("status")
    if status == "gated_no_access":
        return {
            "type": "error",
            "code": "GATED_NO_TOKEN",
            "message": (
                "This model requires accepting a Hugging Face "
                "license and a connected HF token. Open the URL, "
                "accept the terms, paste your token in the model "
                "download step and retry — or switch this model's "
                "engine to Ollama, which needs no token."
            ),
            "url": access.get("url"),
        }
    if status == "not_found":
        return {"type": "error", "code": "NOT_FOUND", "message": f"Model not found on Hugging Face: {model_id}"}
    return None  # network_error / ok → fall through to download
