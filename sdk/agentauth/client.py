"""AgentAuth — agent registration and identity verification client."""

import json
from pathlib import Path

import httpx
import jwt

DEFAULT_REGISTRY_URL = "http://localhost:8000"
DEFAULT_CONFIG_DIR = Path.home() / ".config" / "agentauth"


class AgentAuth:
    """Register agents and verify their identity against the AgentAuth registry."""

    def __init__(
        self,
        registry_url: str = DEFAULT_REGISTRY_URL,
        config_dir: Path | None = None,
    ):
        self.registry_url = registry_url.rstrip("/")
        self.config_dir = config_dir or DEFAULT_CONFIG_DIR
        self._public_key_pem: str | None = None

    def _credentials_path(self, agent_name: str) -> Path:
        creds_dir = self.config_dir / "credentials"
        creds_dir.mkdir(parents=True, exist_ok=True)
        return creds_dir / f"{agent_name}.json"

    def register(self, name: str, description: str | None = None, email: str | None = None) -> dict:
        """Register a new agent.

        Returns response with:
        - registry_secret_key: ONLY for registry API calls, never send to platforms
        - platform_proof_token: JWT to send to platforms, reusable until expiry
        - platform_proof_token_expires_in_seconds: seconds until proof token expires

        If email is provided, a verification link will be generated.
        Once verified, the agent becomes Tier 2 (email-linked).

        Saves credentials to ~/.config/agentauth/credentials/<name>.json.
        """
        payload = {"name": name, "description": description}
        if email is not None:
            payload["email"] = email
        resp = httpx.post(
            f"{self.registry_url}/v1/agents/register",
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()

        # Save credentials locally
        path = self._credentials_path(name)
        path.write_text(json.dumps({
            "name": name,
            "registry_secret_key": data["registry_secret_key"],
        }, indent=2))
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

    def get_registry_secret_key(self, agent_name: str) -> str:
        """Get the registry secret key for an agent. ONLY for registry API calls."""
        return self.load_credentials(agent_name)["registry_secret_key"]

    def registry_auth_headers(self, agent_name: str) -> dict[str, str]:
        """Get Authorization headers for registry API calls ONLY.

        NEVER send these headers to platforms — use platform_proof_headers() instead.
        """
        key = self.get_registry_secret_key(agent_name)
        return {"Authorization": f"Bearer {key}"}

    def link_email(self, agent_name: str, email: str) -> dict:
        """Link an email to an already-registered agent. Triggers verification.

        A verification link will be generated. Once the human clicks it,
        the agent becomes verified (Tier 2).
        """
        resp = httpx.post(
            f"{self.registry_url}/v1/agents/me/email",
            json={"email": email},
            headers=self.registry_auth_headers(agent_name),
        )
        resp.raise_for_status()
        return resp.json()

    def get_platform_proof_token(self, agent_name: str) -> str:
        """Get a JWT proof token for verifying identity on platforms.

        Send this token to platforms instead of your registry secret key.
        The token is reusable until it expires (default: 5 minutes).
        Platforms verify it via the registry or locally using the public key.
        """
        resp = httpx.post(
            f"{self.registry_url}/v1/agents/me/proof",
            headers=self.registry_auth_headers(agent_name),
        )
        resp.raise_for_status()
        return resp.json()["platform_proof_token"]

    def platform_proof_headers(self, agent_name: str) -> dict[str, str]:
        """Get Authorization headers with a proof token for use on platforms.

        Safe to send to any platform. The proof token is reusable until
        it expires (default: 5 minutes).
        """
        token = self.get_platform_proof_token(agent_name)
        return {"Authorization": f"Bearer {token}"}

    def get_me(self, agent_name: str) -> dict:
        """Fetch the agent's own profile from the registry."""
        resp = httpx.get(
            f"{self.registry_url}/v1/agents/me",
            headers=self.registry_auth_headers(agent_name),
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
            headers={"Authorization": f"Bearer {creds['registry_secret_key']}"},
        )
        # Clean up local credentials regardless
        self._credentials_path(agent_name).unlink(missing_ok=True)

        if resp.status_code == 403:
            return False
        resp.raise_for_status()
        return True

    # --- Platform-side token verification ---

    def get_public_key(self) -> str:
        """Fetch the registry's public key for local JWT verification.

        The key is cached after the first call. Platforms use this to verify
        platform_proof_tokens locally without calling the registry each time.
        """
        if self._public_key_pem is None:
            resp = httpx.get(f"{self.registry_url}/.well-known/jwks.json")
            resp.raise_for_status()
            self._public_key_pem = resp.json()["public_key_pem"]
        return self._public_key_pem

    def verify_proof_token(self, token: str) -> dict | None:
        """Verify a platform_proof_token locally using the registry's public key.

        Returns the decoded payload (sub, description, verified, exp, etc.)
        on success, None on invalid or expired token.

        This is Option C — no registry call needed per verification.
        The public key is fetched once and cached.
        """
        public_key = self.get_public_key()
        try:
            return jwt.decode(token, public_key, algorithms=["ES256"])
        except jwt.InvalidTokenError:
            return None

    def verify_proof_token_via_registry(
        self, token: str, platform_secret_key: str | None = None
    ) -> dict | None:
        """Verify a platform_proof_token by calling the registry.

        Returns agent info (name, description, verified, active) on success,
        None on invalid or expired token.

        If platform_secret_key is provided, it is sent as Bearer auth to get
        the higher rate limit (300/min vs 30/min for unregistered callers).

        This is Option A — simple but requires a network call per verification.
        """
        headers = {}
        if platform_secret_key:
            headers["Authorization"] = f"Bearer {platform_secret_key}"
        resp = httpx.get(f"{self.registry_url}/v1/verify-proof/{token}", headers=headers)
        if resp.status_code != 200:
            return None
        return resp.json()

    async def verify_proof_token_via_registry_async(
        self, token: str, platform_secret_key: str | None = None
    ) -> dict | None:
        """Async version of verify_proof_token_via_registry.

        Returns agent info (name, description, verified, active) on success,
        None on invalid or expired token.

        If platform_secret_key is provided, it is sent as Bearer auth to get
        the higher rate limit (300/min vs 30/min for unregistered callers).
        """
        headers = {}
        if platform_secret_key:
            headers["Authorization"] = f"Bearer {platform_secret_key}"
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.registry_url}/v1/verify-proof/{token}", headers=headers
            )
        if resp.status_code != 200:
            return None
        return resp.json()

    # --- Platform registration ---

    def _platform_credentials_path(self, platform_name: str) -> Path:
        """Path to platform credentials file."""
        plat_dir = self.config_dir / "platforms"
        plat_dir.mkdir(parents=True, exist_ok=True)
        return plat_dir / f"{platform_name}.json"

    def register_platform(self, name: str, domain: str, email: str | None = None) -> dict:
        """Register a new platform.

        Returns response with platform_secret_key (shown once).
        Saves credentials to ~/.config/agentauth/platforms/<name>.json.
        """
        payload = {"name": name, "domain": domain}
        if email is not None:
            payload["email"] = email
        resp = httpx.post(f"{self.registry_url}/v1/platforms/register", json=payload)
        resp.raise_for_status()
        data = resp.json()

        path = self._platform_credentials_path(name)
        path.write_text(json.dumps({
            "name": name,
            "platform_secret_key": data["platform_secret_key"],
        }, indent=2))
        path.chmod(0o600)

        return data

    async def register_platform_async(self, name: str, domain: str, email: str | None = None) -> dict:
        """Async version of register_platform."""
        payload = {"name": name, "domain": domain}
        if email is not None:
            payload["email"] = email
        async with httpx.AsyncClient() as client:
            resp = await client.post(f"{self.registry_url}/v1/platforms/register", json=payload)
        resp.raise_for_status()
        data = resp.json()

        path = self._platform_credentials_path(name)
        path.write_text(json.dumps({
            "name": name,
            "platform_secret_key": data["platform_secret_key"],
        }, indent=2))
        path.chmod(0o600)

        return data

    def get_platform(self, platform_name: str) -> dict:
        """Look up any platform's public profile."""
        resp = httpx.get(f"{self.registry_url}/v1/platforms/{platform_name}")
        resp.raise_for_status()
        return resp.json()

    async def get_platform_async(self, platform_name: str) -> dict:
        """Async version of get_platform."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{self.registry_url}/v1/platforms/{platform_name}")
        resp.raise_for_status()
        return resp.json()

    def revoke_platform(self, platform_name: str) -> bool:
        """Revoke a platform from the registry and delete local credentials."""
        path = self._platform_credentials_path(platform_name)
        if not path.exists():
            raise FileNotFoundError(
                f"No credentials found for platform '{platform_name}'. Register it first."
            )
        creds = json.loads(path.read_text())
        resp = httpx.delete(
            f"{self.registry_url}/v1/platforms/{platform_name}",
            headers={"Authorization": f"Bearer {creds['platform_secret_key']}"},
        )
        path.unlink(missing_ok=True)

        if resp.status_code == 403:
            return False
        resp.raise_for_status()
        return True

    async def revoke_platform_async(self, platform_name: str) -> bool:
        """Async version of revoke_platform."""
        path = self._platform_credentials_path(platform_name)
        if not path.exists():
            raise FileNotFoundError(
                f"No credentials found for platform '{platform_name}'. Register it first."
            )
        creds = json.loads(path.read_text())
        async with httpx.AsyncClient() as client:
            resp = await client.delete(
                f"{self.registry_url}/v1/platforms/{platform_name}",
                headers={"Authorization": f"Bearer {creds['platform_secret_key']}"},
            )
        path.unlink(missing_ok=True)

        if resp.status_code == 403:
            return False
        resp.raise_for_status()
        return True

    # --- Agent reporting (by platforms) ---

    def report_agent(self, platform_secret_key: str, agent_name: str) -> bool:
        """Report an agent. Requires platform_secret_key for auth. Returns True on success."""
        resp = httpx.post(
            f"{self.registry_url}/v1/agents/{agent_name}/reports",
            headers={"Authorization": f"Bearer {platform_secret_key}"},
        )
        if resp.status_code == 409:
            return False  # Already reported
        resp.raise_for_status()
        return True

    async def report_agent_async(self, platform_secret_key: str, agent_name: str) -> bool:
        """Async version of report_agent."""
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self.registry_url}/v1/agents/{agent_name}/reports",
                headers={"Authorization": f"Bearer {platform_secret_key}"},
            )
        if resp.status_code == 409:
            return False
        resp.raise_for_status()
        return True

    def retract_report(self, platform_secret_key: str, agent_name: str) -> bool:
        """Retract a report against an agent. Returns True on success, False if no report exists."""
        resp = httpx.delete(
            f"{self.registry_url}/v1/agents/{agent_name}/reports",
            headers={"Authorization": f"Bearer {platform_secret_key}"},
        )
        if resp.status_code == 404:
            return False
        resp.raise_for_status()
        return True

    async def retract_report_async(self, platform_secret_key: str, agent_name: str) -> bool:
        """Async version of retract_report."""
        async with httpx.AsyncClient() as client:
            resp = await client.delete(
                f"{self.registry_url}/v1/agents/{agent_name}/reports",
                headers={"Authorization": f"Bearer {platform_secret_key}"},
            )
        if resp.status_code == 404:
            return False
        resp.raise_for_status()
        return True

    def get_agent_reports(self, agent_name: str) -> dict:
        """Get report summary for an agent. Public — no auth needed."""
        resp = httpx.get(f"{self.registry_url}/v1/agents/{agent_name}/reports")
        resp.raise_for_status()
        return resp.json()

    async def get_agent_reports_async(self, agent_name: str) -> dict:
        """Async version of get_agent_reports."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{self.registry_url}/v1/agents/{agent_name}/reports")
        resp.raise_for_status()
        return resp.json()
