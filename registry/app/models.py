"""Registry data models — flat identity, one key per agent."""

from datetime import UTC, datetime

from pydantic import BaseModel, Field


class RegisterAgentRequest(BaseModel):
    name: str = Field(..., description="Globally unique agent name")
    description: str | None = Field(None, description="What this agent does")


class AgentResponse(BaseModel):
    name: str
    description: str | None = None
    api_key: str | None = None  # Only included on registration response
    public_key: str | None = None  # Hex-encoded, for platform verification
    created_at: datetime
    active: bool = True


class AgentListResponse(BaseModel):
    agents: list[AgentResponse]
    count: int
