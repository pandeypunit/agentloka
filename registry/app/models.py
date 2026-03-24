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
    api_key: str | None = None  # Only included on registration response
    verified: bool = False  # True once email is verified
    created_at: datetime
    active: bool = True


class LinkEmailRequest(BaseModel):
    email: str = Field(..., description="Email address to link and verify")


class AgentListResponse(BaseModel):
    agents: list[AgentResponse]
    count: int
