"""Simple Bearer token authentication."""

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
        raise HTTPException(status_code=401, detail="Invalid API key")

    return agent.name
