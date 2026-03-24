"""Agent identity model."""

from pydantic import BaseModel, Field
import re

AGENT_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,31}$")


def validate_agent_name(name: str) -> str:
    """Validate agent name: 2-32 chars, lowercase, numbers, underscores, starts with letter."""
    if not AGENT_NAME_PATTERN.match(name):
        raise ValueError(
            "Agent name must be 2-32 characters, start with a letter, "
            "and contain only lowercase letters, numbers, and underscores."
        )
    return name


class AgentIdentity(BaseModel):
    """Represents an agent's identity in the AgentAuth system."""

    name: str = Field(..., description="Globally unique agent name")
    description: str | None = Field(None, description="What this agent does")
    public_key: str = Field(..., description="Hex-encoded Ed25519 public key")
    master_public_key: str = Field(
        ..., description="Hex-encoded master public key that owns this agent"
    )

    def model_post_init(self, __context) -> None:
        validate_agent_name(self.name)
