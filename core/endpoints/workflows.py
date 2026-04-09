"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/endpoints/workflows.py
Description: Workflow engine stub — Not Implemented (501).
             Planned for v0.9.1+ (3-4 months post-launch).
             Registered so /v1/ metadata is honest about its status.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from fastapi import APIRouter, HTTPException

router_workflows = APIRouter(prefix="/workflows", tags=["v1", "workflows"])


@router_workflows.api_route(
    "/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
    include_in_schema=True,
    summary="Workflow engine (Not Implemented — planned v0.9.1+)",
)
async def workflows_not_implemented(path: str):
    """Stub endpoint. Workflow engine planned for v0.9.1+ (~3-4 months post-launch)."""
    raise HTTPException(
        status_code=501,
        detail="Workflow engine not yet implemented. Planned for v0.9.1+ (3-4 months post-launch).",
    )
