"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/endpoints/providers.py
Description: Admin endpoints for external API providers (phase 1):
    key presence and a connection test. Both require the admin API key,
    like the other /admin routes. Neither returns a key value.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import asyncio
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException

from core.providers import check_connection, get_provider, provider_status
from core.security.auth import require_api_key

router_providers = APIRouter(prefix="/admin/providers", tags=["providers-admin"])


@router_providers.get("/status", summary="External providers: key presence (API key required)", response_model=dict, operation_id="providers_status")
async def providers_status(_: str = Depends(require_api_key)) -> Dict[str, Any]:
    """Which providers have a key configured. Never returns the key."""
    return provider_status()


@router_providers.post("/{provider_key}/check", summary="Test the connection to one provider (API key required)", response_model=dict, operation_id="providers_check")
async def providers_check(provider_key: str, _: str = Depends(require_api_key)) -> Dict[str, Any]:
    """One minimal request to the provider. 404 for an unknown provider."""
    if get_provider(provider_key) is None:
        raise HTTPException(status_code=404, detail={"error": "unknown_provider"})
    return await asyncio.to_thread(check_connection, provider_key)


def get_router() -> APIRouter:
    """Return the providers admin router."""
    return router_providers
