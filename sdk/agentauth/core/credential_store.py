"""Credential store — reads and writes agent credentials to disk.

Stored at ~/.config/agentauth/credentials/ with one JSON file per agent.
Separated from master key storage for security isolation.
"""

import json
from pathlib import Path

from agentauth.core.credentials import AgentCredentials

DEFAULT_CONFIG_DIR = Path.home() / ".config" / "agentauth"
CREDENTIALS_DIR = "credentials"


class CredentialStore:
    """File-based credential store for agent credentials."""

    def __init__(self, config_dir: Path | None = None):
        self.config_dir = config_dir or DEFAULT_CONFIG_DIR
        self.credentials_dir = self.config_dir / CREDENTIALS_DIR
        self.credentials_dir.mkdir(parents=True, exist_ok=True)

    def _agent_path(self, agent_name: str) -> Path:
        return self.credentials_dir / f"{agent_name}.json"

    def save(self, creds: AgentCredentials) -> Path:
        """Save agent credentials to disk."""
        path = self._agent_path(creds.agent_name)
        path.write_text(creds.model_dump_json(indent=2))
        return path

    def load(self, agent_name: str) -> AgentCredentials:
        """Load agent credentials from disk.

        Raises:
            FileNotFoundError: If agent credentials don't exist.
        """
        path = self._agent_path(agent_name)
        if not path.exists():
            raise FileNotFoundError(
                f"No credentials found for agent '{agent_name}'. "
                f"Register it first with `agentauth register`."
            )
        return AgentCredentials.model_validate_json(path.read_text())

    def exists(self, agent_name: str) -> bool:
        """Check if credentials exist for an agent."""
        return self._agent_path(agent_name).exists()

    def list_agents(self) -> list[AgentCredentials]:
        """List all stored agent credentials."""
        agents = []
        for path in sorted(self.credentials_dir.glob("*.json")):
            agents.append(AgentCredentials.model_validate_json(path.read_text()))
        return agents

    def delete(self, agent_name: str) -> bool:
        """Delete agent credentials. Returns True if deleted, False if not found."""
        path = self._agent_path(agent_name)
        if path.exists():
            path.unlink()
            return True
        return False
