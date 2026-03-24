"""AgentAuth Registry — flat identity, API key verification."""

import logging
import os
import re

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse

from registry.app.auth import get_authenticated_agent
from registry.app.models import AgentListResponse, AgentResponse, LinkEmailRequest, RegisterAgentRequest
from registry.app.skill import get_skill_md
from registry.app.store import registry_store

AGENT_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,31}$")
REGISTRY_BASE_URL = os.environ.get("AGENTAUTH_BASE_URL", "http://localhost:8000")

log = logging.getLogger("agentauth.registry")

app = FastAPI(
    title="AgentAuth Registry",
    description="The identity layer for AI agents",
    version="0.1.0",
)


@app.get("/", include_in_schema=False)
@app.get("/skill.md", include_in_schema=False)
async def skill_page():
    """Serve onboarding instructions as markdown — the entry point for agents."""
    return get_skill_md()


@app.post("/v1/agents/register", response_model=AgentResponse, status_code=201)
async def register_agent(req: RegisterAgentRequest):
    """Register a new agent. No auth needed. Returns an API key (shown once)."""
    if not AGENT_NAME_PATTERN.match(req.name):
        raise HTTPException(
            status_code=422,
            detail="Agent name must be 2-32 characters, start with a lowercase letter, "
            "and contain only lowercase letters, numbers, and underscores.",
        )

    result, verification_token = registry_store.register_agent(req.name, req.description, req.email)
    if result is None:
        raise HTTPException(status_code=409, detail=f"Agent name '{req.name}' is already taken")

    if verification_token:
        verify_url = f"{REGISTRY_BASE_URL}/v1/verify/{verification_token}"
        # In production, send an actual email. For now, log the URL.
        log.info("Verification URL for agent '%s': %s", req.name, verify_url)
        print(f"\n  Verification email for '{req.name}': {verify_url}\n")

    return result


@app.get("/v1/verify/{token}")
async def verify_email(token: str):
    """Verify an agent's email. Human clicks this link from the verification email."""
    agent_name = registry_store.verify_email(token)
    if not agent_name:
        raise HTTPException(status_code=404, detail="Invalid or expired verification link")
    return HTMLResponse(
        content=f"<h1>Verified!</h1><p>Agent <strong>{agent_name}</strong> is now email-verified.</p>",
        status_code=200,
    )


@app.get("/v1/agents/me", response_model=AgentResponse)
async def get_me(request: Request):
    """Get your agent's profile. Requires API key to verify identity."""
    agent_name = await get_authenticated_agent(request)
    agent = registry_store.get_agent(agent_name)
    return agent


@app.post("/v1/agents/me/email")
async def link_email(req: LinkEmailRequest, request: Request):
    """Link an email to your agent. Triggers a verification email."""
    agent_name = await get_authenticated_agent(request)

    token = registry_store.link_email(agent_name, req.email)
    verify_url = f"{REGISTRY_BASE_URL}/v1/verify/{token}"

    # In production, send an actual email. For now, log the URL.
    log.info("Verification URL for agent '%s': %s", agent_name, verify_url)
    print(f"\n  Verification email for '{agent_name}': {verify_url}\n")

    return {"agent_name": agent_name, "message": "Verification email sent. Check your inbox."}


@app.get("/v1/agents/{agent_name}", response_model=AgentResponse)
async def get_agent(agent_name: str):
    """Look up an agent. Public endpoint — platforms call this to verify."""
    agent = registry_store.get_agent(agent_name)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


@app.get("/v1/agents", response_model=AgentListResponse)
async def list_agents():
    """List all registered agents. Public endpoint."""
    agents = registry_store.list_agents()
    return AgentListResponse(agents=agents, count=len(agents))


@app.delete("/v1/agents/{agent_name}")
async def revoke_agent(agent_name: str, request: Request):
    """Revoke (delete) an agent. Requires the agent's API key."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    api_key = auth_header[7:]
    success = registry_store.revoke_agent(agent_name, api_key)
    if not success:
        raise HTTPException(status_code=403, detail="Invalid API key or agent not found")
    return {"name": agent_name, "revoked": True}
