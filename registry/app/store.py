"""In-memory store — flat identity, one API key per agent."""

import secrets
from datetime import UTC, datetime

from registry.app.models import AgentResponse


class RegistryStore:
    """In-memory store for agents. Replace with a database for production."""

    def __init__(self):
        self._agents: dict[str, AgentResponse] = {}  # name -> AgentResponse
        self._keys: dict[str, str] = {}               # api_key -> agent name
        self._emails: dict[str, str] = {}             # agent name -> email (only after verification)
        self._pending_verifications: dict[str, dict] = {}  # token -> {"agent_name", "email"}

    @staticmethod
    def _generate_api_key() -> str:
        return "agentauth_" + secrets.token_hex(24)

    @staticmethod
    def _generate_verification_token() -> str:
        return secrets.token_urlsafe(32)

    def register_agent(
        self, name: str, description: str | None, email: str | None = None
    ) -> tuple[AgentResponse | None, str | None]:
        """Register a new agent. Returns (agent, verification_token) or (None, None) if name is taken."""
        if name in self._agents:
            return None, None

        api_key = self._generate_api_key()
        agent = AgentResponse(
            name=name,
            description=description,
            api_key=api_key,
            verified=False,
            created_at=datetime.now(UTC),
            active=True,
        )
        self._agents[name] = agent
        self._keys[api_key] = name

        verification_token = None
        if email:
            verification_token = self._generate_verification_token()
            self._pending_verifications[verification_token] = {
                "agent_name": name,
                "email": email,
            }

        return agent, verification_token

    def verify_email(self, token: str) -> str | None:
        """Verify an email token. Returns agent name on success, None on failure."""
        pending = self._pending_verifications.pop(token, None)
        if not pending:
            return None

        agent_name = pending["agent_name"]
        email = pending["email"]

        agent = self._agents.get(agent_name)
        if not agent:
            return None

        # Store verified email and mark agent as verified
        self._emails[agent_name] = email
        self._agents[agent_name] = agent.model_copy(update={"verified": True})
        return agent_name

    def link_email(self, agent_name: str, email: str) -> str:
        """Link an email to an existing agent. Returns a verification token."""
        token = self._generate_verification_token()
        self._pending_verifications[token] = {
            "agent_name": agent_name,
            "email": email,
        }
        return token

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
        self._emails.pop(name, None)
        return True


registry_store = RegistryStore()
