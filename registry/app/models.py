"""Registry data models."""

from datetime import UTC, datetime

from pydantic import BaseModel, Field


# --- Request models ---

class RegisterKeyRequest(BaseModel):
    public_key: str = Field(..., description="Hex-encoded 32-byte Ed25519 public key")
    label: str = Field("default", description="Human-readable label for this key")


class RegisterAgentRequest(BaseModel):
    agent_name: str = Field(..., description="Globally unique agent name")
    agent_public_key: str = Field(..., description="Hex-encoded agent public key")
    master_public_key: str = Field(..., description="Hex-encoded master public key")
    description: str | None = Field(None, description="What this agent does")


# --- Response models ---

class KeyResponse(BaseModel):
    key_id: str
    public_key: str
    label: str
    created_at: datetime
    agent_count: int = 0


class AgentResponse(BaseModel):
    agent_name: str
    agent_public_key: str
    master_public_key: str
    description: str | None = None
    created_at: datetime
    active: bool = True


class AgentListResponse(BaseModel):
    agents: list[AgentResponse]
    count: int


class RevokeKeyResponse(BaseModel):
    revoked: bool = True
    agents_revoked: int


class RevokeAgentResponse(BaseModel):
    agent_name: str
    revoked: bool = True
