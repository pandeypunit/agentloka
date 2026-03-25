"""Registry data models — flat identity, one key per agent."""

from datetime import UTC, datetime

from pydantic import BaseModel, Field


class RegisterAgentRequest(BaseModel):
    name: str = Field(..., description="Globally unique agent name")
    description: str | None = Field(None, description="What this agent does")
    email: str | None = Field(None, description="Optional email for verification (Tier 2)")


class AgentResponse(BaseModel):
    name: str
    description: str | None = None
    registry_secret_key: str | None = Field(
        None,
        description="Secret key for registry API calls only. "
        "NEVER send this to any platform — only to the AgentAuth registry.",
    )
    platform_proof_token: str | None = Field(
        None,
        description="JWT token to send to platforms for identity verification. "
        "Reusable until it expires. Get a new one from POST /v1/agents/me/proof.",
    )
    platform_proof_token_expires_in_seconds: int | None = Field(
        None,
        description="Seconds until platform_proof_token expires.",
    )
    verified: bool = False  # True once email is verified
    created_at: datetime
    active: bool = True


class LinkEmailRequest(BaseModel):
    email: str = Field(..., description="Email address to link and verify")


class ProofTokenResponse(BaseModel):
    platform_proof_token: str = Field(
        description="JWT token to send to platforms. Reusable until expiry."
    )
    agent_name: str
    expires_in_seconds: int = Field(
        description="Seconds until the proof token expires."
    )


class ProofVerifyResponse(BaseModel):
    name: str
    description: str | None = None
    verified: bool = False
    active: bool = True


class AgentListResponse(BaseModel):
    agents: list[AgentResponse]
    count: int
