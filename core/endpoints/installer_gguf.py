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

# SSRF/disk-fill guard per a _stream_gguf (NEXE-SRV-WS2-01). El router
# /installer és unauth + CSRF-exempt i model_id arriba verbatim, així que una
# pàgina web cross-origin podria fer-lo servir per fer un fetch cec a un host
# intern (p.ex. http://127.0.0.1:11434/api/tags) o per omplir el disc amb un cos
# infinit. Restringim el fetch a https + host HF, imposem un cap de mida i un
# timeout de lectura finit, i rebutgem les redireccions fora de l'allow-list.
_GGUF_MAX_BYTES = 100 * 1024**3        # 100 GiB — sostre finit anti disk-fill

_GGUF_MAX_REDIRECTS = 5                 # redireccions HF→CDN acotades

_GGUF_READ_TIMEOUT_S = 60.0            # sense bytes durant 60s → avorta (no penja)

def _is_allowed_gguf_url(url: str) -> bool:
    """True iff ``url`` és una font GGUF baixable: una URL https amb host a
    l'allow-list del HuggingFace Hub.

    Guarda SSRF/disk-fill de _stream_gguf: reutilitza ``installer_hf._is_hf_hub_url`` per al
    host i exigeix a més esquema ``https``, de manera que ni ``http://`` ni un
    host intern (``http://127.0.0.1:11434/api/tags``) ni un host de catàleg
    arbitrari poden arribar mai al fetch.
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

    SSRF/disk-fill guard (NEXE-SRV-WS2-01): ``model_id`` ha de ser una URL https
    amb host del HuggingFace Hub. Qualsevol altre esquema/host es rebutja abans
    del fetch (evita el fetch cec a hosts interns), s'imposa un cap de mida i un
    timeout de lectura finit, i es rebutgen les redireccions que surtin de
    l'allow-list.
    """
    import httpx

    # Guarda d'entrada: cap fetch cap a un target no permès.
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
    # header. model_id ja està restringit a hosts HF per la guarda de dalt, així
    # que el token només pot anar a HF. En seguir redireccions manualment
    # eliminem l'Authorization en canviar de host (el CDN de HF usa URLs signades
    # i no el necessita), reproduint l'antic strip cross-origin d'httpx.
    headers: dict[str, str] = {}
    if installer_hf._is_hf_hub_url(model_id):
        token = await installer_hf._ensure_hf_token_in_env()
        if token:
            headers["Authorization"] = f"Bearer {token}"

    # Timeout finit: read=60s avorta un stream que es queda mut sense trencar les
    # baixades llargues legítimes (cada chunk rebut reinicia el rellotge).
    timeout = httpx.Timeout(
        connect=30.0, read=_GGUF_READ_TIMEOUT_S, write=60.0, pool=30.0,
    )
    # follow_redirects=False: seguim els salts a mà per validar-ne cada destí
    # contra l'allow-list (un 30x cap a un host no-HF avorta).
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
                    # Canvi de host → no reenviïs el bearer (strip cross-origin).
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
                            # Cap superat en streaming (cos sense content-length o
                            # amb un de mentider): avorta i neteja el parcial.
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
        # Massa redireccions consecutives → avorta.
        yield {
            "type": "error",
            "code": "TOO_MANY_REDIRECTS",
            "message": "GGUF download exceeded the redirect limit.",
        }
