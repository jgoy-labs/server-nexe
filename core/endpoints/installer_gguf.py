"""The GGUF install path of the wizard: a direct URL download.

Split out of ``core.endpoints.installer`` (finding #969). Unlike MLX, this
path takes a URL the caller supplies, which is why the SSRF allowlist, the
redirect ceiling and the size cap live here and not in the shared layer: they
guard THIS entry point.

The three ceilings are deliberate and tested (`test_installer_gguf_ssrf.py`):
a finite byte cap so a hostile Content-Length cannot fill the disk, a bounded
number of HF→CDN redirects, and a read timeout so a silent socket aborts
instead of hanging the wizard.
"""

from __future__ import annotations

import logging
from typing import AsyncIterator
from urllib.parse import urlparse

from fastapi import Request

from core.endpoints import installer_hf, installer_shared

logger = logging.getLogger(__name__)

# SSRF/disk-fill guard for _stream_gguf (NEXE-SRV-WS2-01). The
# /installer router is unauth + CSRF-exempt and model_id arrives verbatim, so a
# cross-origin web page could use it for a blind fetch to an internal
# host (e.g. http://127.0.0.1:11434/api/tags) or to fill the disk with an
# infinite body. We restrict the fetch to https + an HF host, impose a size cap and a
# finite read timeout, and reject redirects off the allow-list.
_GGUF_MAX_BYTES = 100 * 1024**3        # 100 GiB — finite ceiling against disk-fill

_GGUF_MAX_REDIRECTS = 5                 # bounded HF→CDN redirects

_GGUF_READ_TIMEOUT_S = 60.0            # no bytes for 60s → abort (does not hang)

def _is_allowed_gguf_url(url: str) -> bool:
    """True iff ``url`` is a downloadable GGUF source: an https URL whose host is on
    the HuggingFace Hub allow-list.

    SSRF/disk-fill guard of _stream_gguf: reuses ``installer_hf._is_hf_hub_url`` for the
    host and also requires the ``https`` scheme, so neither ``http://`` nor an
    internal host (``http://127.0.0.1:11434/api/tags``) nor an arbitrary catalog
    host can ever reach the fetch.
    """
    try:
        scheme = (urlparse(url).scheme or "").lower()
    except ValueError:
        return False
    if scheme != "https":
        return False
    return installer_hf._is_hf_hub_url(url)

async def _stream_gguf(model_id: str, request: Request) -> AsyncIterator[dict]:
    """Download a GGUF model via HTTP with progress reporting.

    SSRF/disk-fill guard (NEXE-SRV-WS2-01): ``model_id`` must be an https URL
    on a HuggingFace Hub host. Any other scheme/host is rejected before
    the fetch (no blind fetch to internal hosts), a size cap and a
    finite read timeout are imposed, and redirects that leave the
    allow-list are rejected.
    """
    import httpx

    # Entry guard: no fetch to a target that is not allowed.
    if not _is_allowed_gguf_url(model_id):
        yield {
            "type": "error",
            "code": "INVALID_MODEL_URL",
            "message": (
                "GGUF download URL must be an https:// URL on the Hugging Face "
                "Hub (huggingface.co / hf.co)."
            ),
        }
        return

    filename = installer_shared._safe_model_basename(model_id)
    dest = installer_shared._models_dir() / filename
    dest.parent.mkdir(parents=True, exist_ok=True)

    # B255: a gated GGUF on the HF Hub needs an "Authorization: Bearer <HF_TOKEN>"
    # header. model_id is already restricted to HF hosts by the guard above, so
    # the token can only go to HF. When following redirects by hand
    # we drop Authorization on a host change (the HF CDN uses signed URLs
    # and does not need it), reproducing httpx's old cross-origin strip.
    headers: dict[str, str] = {}
    if installer_hf._is_hf_hub_url(model_id):
        token = await installer_hf._ensure_hf_token_in_env()
        if token:
            headers["Authorization"] = f"Bearer {token}"

    # Finite timeout: read=60s aborts a stream that goes silent without breaking
    # legitimate long downloads (each received chunk restarts the clock).
    timeout = httpx.Timeout(
        connect=30.0, read=_GGUF_READ_TIMEOUT_S, write=60.0, pool=30.0,
    )
    # follow_redirects=False: we follow hops by hand to validate each target
    # against the allow-list (a 30x to a non-HF host aborts).
    async with httpx.AsyncClient(follow_redirects=False, timeout=timeout) as client:
        url = model_id
        req_headers = dict(headers)
        for _hop in range(_GGUF_MAX_REDIRECTS + 1):
            async with client.stream("GET", url, headers=req_headers) as resp:
                if resp.is_redirect:
                    location = resp.headers.get("location", "")
                    next_url = str(resp.url.join(location))
                    if not _is_allowed_gguf_url(next_url):
                        yield {
                            "type": "error",
                            "code": "REDIRECT_OFF_ALLOWLIST",
                            "message": (
                                "GGUF download redirected off the Hugging Face "
                                "allow-list."
                            ),
                        }
                        return
                    # Host change → do not forward the bearer (cross-origin strip).
                    if urlparse(next_url).hostname != urlparse(url).hostname:
                        req_headers = {
                            k: v for k, v in req_headers.items()
                            if k.lower() != "authorization"
                        }
                    url = next_url
                    continue

                resp.raise_for_status()
                total = int(resp.headers.get("content-length", 0) or 0)
                if total and total > _GGUF_MAX_BYTES:
                    yield {
                        "type": "error",
                        "code": "MODEL_TOO_LARGE",
                        "message": (
                            f"GGUF exceeds the {_GGUF_MAX_BYTES} byte cap "
                            f"(content-length={total})."
                        ),
                    }
                    return
                downloaded = 0
                last_pct = -1
                with dest.open("wb") as fh:
                    async for chunk in resp.aiter_bytes(chunk_size=1024 * 256):
                        if await request.is_disconnected():
                            return
                        downloaded += len(chunk)
                        if downloaded > _GGUF_MAX_BYTES:
                            # Cap exceeded while streaming (body with no content-length or
                            # with a lying one): abort and delete the partial.
                            fh.close()
                            try:
                                dest.unlink()
                            except OSError:
                                pass
                            yield {
                                "type": "error",
                                "code": "MODEL_TOO_LARGE",
                                "message": (
                                    f"GGUF download exceeded the {_GGUF_MAX_BYTES} "
                                    "byte cap; aborted."
                                ),
                            }
                            return
                        fh.write(chunk)
                        if total:
                            pct = int(downloaded * 100 / total)
                            if pct != last_pct:
                                last_pct = pct
                                yield {"type": "progress", "percent": pct, "speed": "—", "eta": "—"}
                return
        # Too many consecutive redirects → abort.
        yield {
            "type": "error",
            "code": "TOO_MANY_REDIRECTS",
            "message": "GGUF download exceeded the redirect limit.",
        }
