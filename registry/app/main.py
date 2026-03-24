"""AgentAuth Registry — FastAPI application."""

from fastapi import FastAPI, HTTPException, Query, Request

from registry.app.auth import verify_request_signature
from registry.app.models import (
    AgentListResponse,
    AgentResponse,
    KeyResponse,
    RegisterAgentRequest,
    RegisterKeyRequest,
    RevokeAgentResponse,
    RevokeKeyResponse,
)
from registry.app.skill import get_skill_md
from registry.app.store import registry_store

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


# --- Key endpoints ---


@app.post("/v1/keys", response_model=KeyResponse, status_code=201)
async def register_key(req: RegisterKeyRequest):
    """Register a master public key. No auth needed (Tier 1 — pseudonymous)."""
    # Validate key format
    try:
        key_bytes = bytes.fromhex(req.public_key)
        if len(key_bytes) != 32:
            raise ValueError()
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid key: must be 64 hex characters (32 bytes)")

    result = registry_store.register_key(req.public_key, req.label)
    if result is None:
        raise HTTPException(status_code=409, detail="Key already registered")
    return result


@app.get("/v1/keys/{key_id}", response_model=KeyResponse)
async def get_key(key_id: str):
    """Look up a master key by key_id. Public endpoint."""
    record = registry_store.get_key_by_id(key_id)
    if not record:
        raise HTTPException(status_code=404, detail="Key not found")
    return record


@app.get("/v1/keys", response_model=KeyResponse)
async def get_key_by_public_key(public_key: str = Query(...)):
    """Look up a master key by public key hex. Public endpoint."""
    record = registry_store.get_key_by_public_key(public_key)
    if not record:
        raise HTTPException(status_code=404, detail="Key not found")
    return record


@app.delete("/v1/keys/{key_id}", response_model=RevokeKeyResponse)
async def revoke_key(key_id: str, request: Request):
    """Revoke a master key and all its agents. Authenticated."""
    public_key_hex = await verify_request_signature(request)

    # Verify the caller owns this key
    record = registry_store.get_key_by_id(key_id)
    if not record:
        raise HTTPException(status_code=404, detail="Key not found")
    if record.public_key != public_key_hex:
        raise HTTPException(status_code=403, detail="Not your key")

    count = registry_store.revoke_key(key_id)
    return RevokeKeyResponse(agents_revoked=count)


# --- Agent endpoints ---


@app.post("/v1/agents", response_model=AgentResponse, status_code=201)
async def register_agent(request: Request):
    """Register an agent under a master key. Authenticated."""
    public_key_hex = await verify_request_signature(request)

    body = await request.body()
    req = RegisterAgentRequest.model_validate_json(body)

    # Verify the signer is the master key owner
    if req.master_public_key != public_key_hex:
        raise HTTPException(status_code=403, detail="Signature key does not match master_public_key")

    try:
        result = registry_store.register_agent(
            agent_name=req.agent_name,
            agent_public_key=req.agent_public_key,
            master_public_key=req.master_public_key,
            description=req.description,
        )
    except LookupError:
        raise HTTPException(status_code=404, detail="Master key not registered. Register it first via POST /v1/keys")

    if result is None:
        raise HTTPException(status_code=409, detail=f"Agent name '{req.agent_name}' is already taken")
    return result


@app.get("/v1/agents/{agent_name}", response_model=AgentResponse)
async def get_agent(agent_name: str):
    """Look up an agent. Public endpoint — platforms call this to verify."""
    record = registry_store.get_agent(agent_name)
    if not record:
        raise HTTPException(status_code=404, detail="Agent not found")
    return record


@app.get("/v1/agents", response_model=AgentListResponse)
async def list_agents(master_public_key: str = Query(...)):
    """List all agents under a master key. Public endpoint."""
    agents = registry_store.list_agents_by_master(master_public_key)
    return AgentListResponse(agents=agents, count=len(agents))


@app.delete("/v1/agents/{agent_name}", response_model=RevokeAgentResponse)
async def revoke_agent(agent_name: str, request: Request):
    """Revoke an agent. Authenticated — must be signed by owning master key."""
    public_key_hex = await verify_request_signature(request)

    success = registry_store.revoke_agent(agent_name, public_key_hex)
    if not success:
        raise HTTPException(status_code=404, detail="Agent not found or not owned by this key")
    return RevokeAgentResponse(agent_name=agent_name)
