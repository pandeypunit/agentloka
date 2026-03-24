"""In-memory store — flat identity, one API key per agent."""

import secrets
from datetime import UTC, datetime

from registry.app.models import AgentResponse


class RegistryStore:
    """In-memory store for agents. Replace with a database for production."""

    def __init__(self):
        self._agents: dict[str, AgentResponse] = {}  # name -> AgentResponse
        self._keys: dict[str, str] = {}               # api_key -> agent name

    @staticmethod
    def _generate_api_key() -> str:
        return "agentauth_" + secrets.token_hex(24)

    def register_agent(self, name: str, description: str | None) -> AgentResponse | None:
        """Register a new agent. Returns None if name is taken."""
        if name in self._agents:
            return None

        api_key = self._generate_api_key()
        agent = AgentResponse(
            name=name,
            description=description,
            api_key=api_key,
            created_at=datetime.now(UTC),
            active=True,
        )
        self._agents[name] = agent
        self._keys[api_key] = name
        return agent

    def get_agent(self, name: str) -> AgentResponse | None:
        agent = self._agents.get(name)
        if agent:
            # Return without api_key (public lookup)
            return agent.model_copy(update={"api_key": None})
        return None

    def get_agent_by_key(self, api_key: str) -> AgentResponse | None:
        name = self._keys.get(api_key)
        if name:
            return self._agents.get(name)
        return None

    def list_agents(self) -> list[AgentResponse]:
        # Return without api_keys
        return [a.model_copy(update={"api_key": None}) for a in self._agents.values()]

    def revoke_agent(self, name: str, api_key: str) -> bool:
        """Revoke an agent. Must provide the correct API key."""
        agent = self._agents.get(name)
        if not agent or agent.api_key != api_key:
            return False
        self._agents.pop(name)
        self._keys.pop(api_key, None)
        return True


registry_store = RegistryStore()
