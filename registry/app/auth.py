"""Simple Bearer token identity verification."""

import os
import secrets

from fastapi import HTTPException, Request

from registry.app.store import registry_store


async def get_authenticated_agent(request: Request) -> str:
    """Extract and validate Bearer token. Returns agent name.

    Expects: Authorization: Bearer agentauth_xxxxx
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Missing or invalid Authorization header. Expected: Bearer agentauth_xxxxx",
        )

    api_key = auth_header[7:]  # Strip "Bearer "
    agent = registry_store.get_agent_by_key(api_key)
    if not agent:
        raise HTTPException(
            status_code=401,
            detail="Invalid registry_secret_key. Ensure you are sending your registry_secret_key "
            "(starts with 'agentauth_'), not a platform_proof_token. "
            "If you lost your key, it cannot be recovered — register a new agent.",
        )

    return agent.name


async def get_authenticated_admin(request: Request):
    """Validate admin bearer token against AGENTAUTH_ADMIN_TOKEN env var."""
    admin_token = os.environ.get("AGENTAUTH_ADMIN_TOKEN")
    if not admin_token:
        raise HTTPException(status_code=503, detail="Admin reporting is disabled")

    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing admin Authorization header")

    if not secrets.compare_digest(auth_header[7:], admin_token):
        raise HTTPException(status_code=403, detail="Invalid admin token")
