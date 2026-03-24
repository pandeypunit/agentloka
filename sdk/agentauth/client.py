"""AgentAuth — simple agent registration and authentication client."""

import json
from pathlib import Path

import httpx

DEFAULT_REGISTRY_URL = "http://localhost:8000"
DEFAULT_CONFIG_DIR = Path.home() / ".config" / "agentauth"


class AgentAuth:
    """Register and authenticate agents against the AgentAuth registry."""

    def __init__(
        self,
        registry_url: str = DEFAULT_REGISTRY_URL,
        config_dir: Path | None = None,
    ):
        self.registry_url = registry_url.rstrip("/")
        self.config_dir = config_dir or DEFAULT_CONFIG_DIR

    def _credentials_path(self, agent_name: str) -> Path:
        creds_dir = self.config_dir / "credentials"
        creds_dir.mkdir(parents=True, exist_ok=True)
        return creds_dir / f"{agent_name}.json"

    def register(self, name: str, description: str | None = None) -> dict:
        """Register a new agent. Returns response with api_key (shown once).

        Also saves credentials to ~/.config/agentauth/credentials/<name>.json.
        """
        resp = httpx.post(
            f"{self.registry_url}/v1/agents/register",
            json={"name": name, "description": description},
        )
        resp.raise_for_status()
        data = resp.json()

        # Save credentials locally
        path = self._credentials_path(name)
        path.write_text(json.dumps({"name": name, "api_key": data["api_key"]}, indent=2))
        path.chmod(0o600)

        return data

    def load_credentials(self, agent_name: str) -> dict:
        """Load saved credentials for an agent.

        Raises:
            FileNotFoundError: If agent is not registered locally.
        """
        path = self._credentials_path(agent_name)
        if not path.exists():
            raise FileNotFoundError(
                f"No credentials found for agent '{agent_name}'. Register it first."
            )
        return json.loads(path.read_text())

    def get_api_key(self, agent_name: str) -> str:
        """Get the API key for a registered agent."""
        return self.load_credentials(agent_name)["api_key"]

    def auth_headers(self, agent_name: str) -> dict[str, str]:
        """Get Authorization headers for an agent. Use with any HTTP client."""
        api_key = self.get_api_key(agent_name)
        return {"Authorization": f"Bearer {api_key}"}

    def get_me(self, agent_name: str) -> dict:
        """Fetch the agent's own profile from the registry."""
        resp = httpx.get(
            f"{self.registry_url}/v1/agents/me",
            headers=self.auth_headers(agent_name),
        )
        resp.raise_for_status()
        return resp.json()

    def get_agent(self, agent_name: str) -> dict:
        """Look up any agent's public profile."""
        resp = httpx.get(f"{self.registry_url}/v1/agents/{agent_name}")
        resp.raise_for_status()
        return resp.json()

    def list_agents(self) -> list[dict]:
        """List all locally registered agents."""
        creds_dir = self.config_dir / "credentials"
        if not creds_dir.exists():
            return []
        agents = []
        for path in sorted(creds_dir.glob("*.json")):
            agents.append(json.loads(path.read_text()))
        return agents

    def revoke(self, agent_name: str) -> bool:
        """Revoke an agent from the registry and delete local credentials."""
        creds = self.load_credentials(agent_name)
        resp = httpx.delete(
            f"{self.registry_url}/v1/agents/{agent_name}",
            headers={"Authorization": f"Bearer {creds['api_key']}"},
        )
        # Clean up local credentials regardless
        self._credentials_path(agent_name).unlink(missing_ok=True)

        if resp.status_code == 403:
            return False
        resp.raise_for_status()
        return True
