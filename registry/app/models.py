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
    important: str | None = Field(
        None,
        description="Critical security instructions. Read carefully.",
    )
    verified: bool = False  # True once email is verified
    created_at: datetime
    active: bool = True
    report_count: int = 0
    reporting_platforms: list[str] = []


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


# --- Platform models ---


class RegisterPlatformRequest(BaseModel):
    name: str = Field(..., description="Globally unique platform name")
    domain: str = Field(..., description="Platform domain (e.g. microblog.agentloka.ai)")
    description: str | None = Field(None, description="Short description of the platform (max 140 chars)")
    email: str | None = Field(None, description="Optional email for verification")


class AgentReportSummary(BaseModel):
    agent_name: str
    report_count: int = 0
    reporting_platforms: list[str] = []


class PlatformListResponse(BaseModel):
    platforms: list["PlatformResponse"]
    count: int


class PlatformResponse(BaseModel):
    name: str
    domain: str
    description: str | None = None
    platform_secret_key: str | None = Field(
        None,
        description="Secret key for platform API calls. "
        "Shown ONLY ONCE at registration. Send as Bearer token to get higher rate limits.",
    )
    important: str | None = Field(
        None,
        description="Critical security instructions. Read carefully.",
    )
    verified: bool = False
    created_at: datetime
    active: bool = True
