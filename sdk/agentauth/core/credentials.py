"""Credential models for platform-specific auth data."""

from datetime import UTC, datetime

from pydantic import BaseModel, Field


class Credentials(BaseModel):
    """Platform-specific credentials returned after registration."""

    platform: str = Field(..., description="Platform name (e.g. 'moltbook')")
    api_key: str | None = Field(None, description="Platform API key")
    token: str | None = Field(None, description="Auth token")
    expires_at: datetime | None = Field(None, description="Token expiry")


class AgentCredentials(BaseModel):
    """Full credential record for a registered agent — stored on disk."""

    agent_name: str = Field(..., description="Globally unique agent name")
    agent_public_key: str = Field(..., description="Hex-encoded agent public key")
    master_public_key: str = Field(..., description="Hex-encoded master public key")
    platform: str = Field(..., description="Platform this agent is registered on")
    credentials: Credentials = Field(..., description="Platform-specific credentials")
    registered_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
