"""AgentAuth Registry — flat identity, simple API key auth."""

import re

from fastapi import FastAPI, HTTPException, Request

from registry.app.auth import get_authenticated_agent
from registry.app.models import AgentListResponse, AgentResponse, RegisterAgentRequest
from registry.app.skill import get_skill_md
from registry.app.store import registry_store

AGENT_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,31}$")

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

    result = registry_store.register_agent(req.name, req.description)
    if result is None:
        raise HTTPException(status_code=409, detail=f"Agent name '{req.name}' is already taken")
    return result


@app.get("/v1/agents/me", response_model=AgentResponse)
async def get_me(request: Request):
    """Get the authenticated agent's profile. Requires API key."""
    agent_name = await get_authenticated_agent(request)
    agent = registry_store.get_agent(agent_name)
    return agent


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
