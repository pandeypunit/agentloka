"""AgentAuth Registry — flat identity, API key verification."""

import logging
import os
import re
from html import escape

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

import json

from registry.app.auth import get_authenticated_admin, get_authenticated_agent, get_authenticated_platform
from registry.app.models import (
    AgentListResponse,
    AgentReportSummary,
    AgentResponse,
    LinkEmailRequest,
    PlatformListResponse,
    PlatformResponse,
    ProofTokenResponse,
    ProofVerifyResponse,
    RegisterAgentRequest,
    RegisterPlatformRequest,
)
from registry.app.skill import get_skill_md
from registry.app.store import PROOF_TOKEN_TTL_SECONDS, registry_store

AGENT_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,31}$")
REGISTRY_BASE_URL = os.environ.get("AGENTAUTH_BASE_URL", "http://localhost:8000")

log = logging.getLogger("agentauth.registry")

app = FastAPI(
    title="AgentAuth Registry",
    description="The identity layer for AI agents",
    version="0.1.0",
)

# CORS — allow the landing page and any platform to call the registry API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)

# Rate limiter for verify-proof — tiered: 300/min for registered platforms, 30/min per IP otherwise
def _verify_proof_key_func(request: Request) -> str:
    """Return rate limit key: platform name for registered callers, IP for anonymous."""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer platauth_"):
        platform = registry_store.get_platform_by_key(auth_header[7:])
        if platform:
            return f"platform:{platform.name}"
    return get_remote_address(request)


def _verify_proof_limit(key: str) -> str:
    """Return the rate limit string based on the key type."""
    if key.startswith("platform:"):
        return "300/minute"
    return "30/minute"


limiter = Limiter(key_func=_verify_proof_key_func)
app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={
            "detail": "Rate limit exceeded on verify-proof. "
            f"Register your platform at POST {REGISTRY_BASE_URL}/v1/platforms/register "
            "for a higher rate limit (300/min vs 30/min).",
        },
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
            detail=f"Invalid agent name '{req.name}'. "
            "Agent name must be 2-32 characters, start with a lowercase letter, "
            "and contain only lowercase letters, numbers, and underscores. "
            "Examples: my_agent, research_bot_42, data_helper.",
        )

    result, verification_token = registry_store.register_agent(req.name, req.description, req.email)
    if result is None:
        raise HTTPException(
            status_code=409,
            detail=f"Agent name '{req.name}' is already registered. "
            "If this is your agent, use your registry_secret_key to get a fresh proof token: "
            f"POST {REGISTRY_BASE_URL}/v1/agents/me/proof with Authorization: Bearer <your_registry_secret_key>. "
            "If you lost your registry_secret_key, it cannot be recovered — register a new agent with a different name.",
        )

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
        content=f"<h1>Verified!</h1><p>Agent <strong>{escape(agent_name)}</strong> is now email-verified.</p>",
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


@app.post("/v1/agents/me/proof", response_model=ProofTokenResponse)
async def create_proof(request: Request):
    """Get a JWT proof token. Agent sends this to platforms instead of its API key.

    The token is reusable until it expires (default: 5 minutes).
    Platforms can verify it via /v1/verify-proof/{token} (Option A)
    or locally using the public key from /.well-known/jwks.json (Option C).
    """
    agent_name = await get_authenticated_agent(request)
    token = registry_store.create_proof_token(agent_name)
    return ProofTokenResponse(
        platform_proof_token=token,
        agent_name=agent_name,
        expires_in_seconds=PROOF_TOKEN_TTL_SECONDS,
    )


@app.get("/v1/verify-proof/{token}", response_model=ProofVerifyResponse)
@limiter.limit(_verify_proof_limit)
async def verify_proof(request: Request, token: str):
    """Verify a proof token (Option A). Platforms call this — no auth needed.

    Token is reusable — multiple verifications are allowed until expiry.
    Registered platforms (platauth_ Bearer) get 300/min; anonymous callers get 30/min.
    """
    payload = registry_store.verify_proof_token(token)
    if not payload:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired proof token. Proof tokens expire after 5 minutes. "
            f"Get a fresh one: POST {REGISTRY_BASE_URL}/v1/agents/me/proof "
            "with Authorization: Bearer <your_registry_secret_key>.",
        )
    return ProofVerifyResponse(
        name=payload["sub"],
        description=payload.get("description"),
        verified=payload.get("verified", False),
        active=True,
    )


@app.get("/.well-known/jwks.json")
async def jwks():
    """Public key for verifying proof tokens locally (Option C).

    Platforms fetch this once, then verify JWT proof tokens without
    calling the registry on every request.
    """
    return JSONResponse(content={"public_key_pem": registry_store.public_key_pem})


@app.get("/v1/agents/{agent_name}", response_model=AgentResponse)
async def get_agent(agent_name: str):
    """Look up an agent. Public endpoint — platforms call this to verify."""
    agent = registry_store.get_agent(agent_name)
    if not agent:
        raise HTTPException(
            status_code=404,
            detail=f"Agent '{agent_name}' not found. Check the name spelling. "
            f"To register a new agent: POST {REGISTRY_BASE_URL}/v1/agents/register "
            'with {{"name": "your_name", "description": "what you do"}}.',
        )
    return agent


@app.get("/v1/agents", response_model=AgentListResponse)
async def list_agents():
    """List all registered agents. Public endpoint."""
    agents = registry_store.list_agents()
    return AgentListResponse(agents=agents, count=len(agents))


# --- Platform endpoints ---


@app.post("/v1/platforms/register", response_model=PlatformResponse, status_code=201)
async def register_platform(req: RegisterPlatformRequest):
    """Register a new platform. No auth needed. Returns a platform_secret_key (shown once)."""
    if not AGENT_NAME_PATTERN.match(req.name):
        raise HTTPException(
            status_code=422,
            detail=f"Invalid platform name '{req.name}'. "
            "Platform name must be 2-32 characters, start with a lowercase letter, "
            "and contain only lowercase letters, numbers, and underscores.",
        )

    if req.description and len(req.description) > 140:
        raise HTTPException(
            status_code=422,
            detail="Platform description must be 140 characters or fewer.",
        )

    result, verification_token = registry_store.register_platform(
        req.name, req.domain, description=req.description, email=req.email
    )
    if result is None:
        raise HTTPException(
            status_code=409,
            detail=f"Platform name '{req.name}' is already registered.",
        )

    if verification_token:
        verify_url = f"{REGISTRY_BASE_URL}/v1/verify-platform/{verification_token}"
        log.info("Verification URL for platform '%s': %s", req.name, verify_url)
        print(f"\n  Verification email for platform '{req.name}': {verify_url}\n")

    return result


@app.get("/v1/platforms/{platform_name}", response_model=PlatformResponse)
async def get_platform(platform_name: str):
    """Look up a platform. Public endpoint — no secret key in response."""
    platform = registry_store.get_platform(platform_name)
    if not platform:
        raise HTTPException(
            status_code=404,
            detail=f"Platform '{platform_name}' not found.",
        )
    return platform


@app.get("/v1/platforms", response_model=PlatformListResponse)
async def list_platforms():
    """List all active platforms. Public endpoint — shown on the landing page."""
    platforms = registry_store.list_platforms()
    return PlatformListResponse(platforms=platforms, count=len(platforms))


@app.delete("/v1/platforms/{platform_name}")
async def revoke_platform(platform_name: str, request: Request):
    """Revoke (delete) a platform. Requires the platform's secret key."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    secret_key = auth_header[7:]
    success = registry_store.revoke_platform(platform_name, secret_key)
    if not success:
        raise HTTPException(status_code=403, detail="Invalid secret key or platform not found")
    return {"name": platform_name, "revoked": True}


@app.get("/v1/verify-platform/{token}")
async def verify_platform_email(token: str):
    """Verify a platform's email. Human clicks this link from the verification email."""
    platform_name = registry_store.verify_platform_email(token)
    if not platform_name:
        raise HTTPException(status_code=404, detail="Invalid or expired verification link")
    return HTMLResponse(
        content=f"<h1>Verified!</h1><p>Platform <strong>{escape(platform_name)}</strong> is now email-verified.</p>",
        status_code=200,
    )


# --- Agent reports (by registered platforms) ---


@app.post("/v1/agents/{agent_name}/reports", status_code=201)
async def report_agent(agent_name: str, request: Request):
    """Report an agent. Requires platform auth (platauth_ Bearer). One report per platform."""
    platform_name = await get_authenticated_platform(request)

    # Verify agent exists
    agent = registry_store.get_agent(agent_name)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' not found.")

    success = registry_store.report_agent(agent_name, platform_name)
    if not success:
        raise HTTPException(
            status_code=409,
            detail=f"Agent '{agent_name}' is already reported by platform '{platform_name}'. "
            f"To retract: DELETE {REGISTRY_BASE_URL}/v1/agents/{agent_name}/reports",
        )
    return {"agent_name": agent_name, "platform_name": platform_name, "reported": True}


@app.delete("/v1/agents/{agent_name}/reports", status_code=204)
async def retract_report(agent_name: str, request: Request):
    """Retract a report against an agent. Requires platform auth."""
    platform_name = await get_authenticated_platform(request)

    success = registry_store.retract_report(agent_name, platform_name)
    if not success:
        raise HTTPException(
            status_code=404,
            detail=f"No report found from platform '{platform_name}' against agent '{agent_name}'.",
        )


@app.get("/v1/agents/{agent_name}/reports", response_model=AgentReportSummary)
async def get_agent_reports(agent_name: str):
    """Get report summary for an agent. Public endpoint."""
    return registry_store.get_agent_reports(agent_name)


@app.get("/platform.md", include_in_schema=False)
async def platform_skill_page():
    """Serve platform onboarding instructions as markdown."""
    from registry.app.platform_skill import get_platform_md
    return get_platform_md()


@app.get("/v1/admin/stats")
async def admin_stats(request: Request):
    """Admin-only: registry statistics. Requires AGENTAUTH_ADMIN_TOKEN."""
    await get_authenticated_admin(request)
    params = request.query_params
    stats = registry_store.get_admin_stats(
        from_date=params.get("from"), to_date=params.get("to")
    )
    if params.get("format") == "html":
        html = (
            "<html><head><title>AgentAuth Admin</title></head><body>"
            f"<h1>AgentAuth Admin Stats</h1><pre>{json.dumps(stats, indent=2)}</pre>"
            "</body></html>"
        )
        return HTMLResponse(content=html)
    return stats


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
