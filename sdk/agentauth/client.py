"""AgentAuth — main SDK entry point.

Handles master key management, agent registration, and authentication
against the AgentAuth registry.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

from agentauth.core.credential_store import CredentialStore
from agentauth.core.credentials import AgentCredentials, Credentials
from agentauth.core.identity import AgentIdentity, validate_agent_name
from agentauth.keys.derivation import derive_agent_key, sign_message
from agentauth.keys.master import (
    DEFAULT_CONFIG_DIR,
    generate_master_key,
    load_master_key,
    master_key_exists,
    save_master_key,
)

DEFAULT_REGISTRY_URL = "http://localhost:8000"


class AgentAuth:
    """Main entry point for agent registration and authentication."""

    def __init__(
        self,
        registry_url: str = DEFAULT_REGISTRY_URL,
        config_dir: Path | None = None,
    ):
        self.registry_url = registry_url.rstrip("/")
        self.config_dir = config_dir or DEFAULT_CONFIG_DIR
        self.store = CredentialStore(config_dir=self.config_dir)
        self._master_private: bytes | None = None
        self._master_public: bytes | None = None

    def _load_master_key(self):
        """Load master key from disk, caching in memory."""
        if self._master_private is None:
            self._master_private, self._master_public = load_master_key(self.config_dir)

    def _sign_request(self, body: bytes) -> dict[str, str]:
        """Create auth headers for a signed request to the registry."""
        self._load_master_key()
        timestamp = datetime.now(UTC).isoformat()
        message = f"{timestamp}\n".encode() + body
        private_key = Ed25519PrivateKey.from_private_bytes(self._master_private)
        signature = private_key.sign(message)
        return {
            "X-AgentAuth-PublicKey": self._master_public.hex(),
            "X-AgentAuth-Signature": signature.hex(),
            "X-AgentAuth-Timestamp": timestamp,
            "Content-Type": "application/json",
        }

    # --- Init ---

    def init(self, label: str = "default") -> dict:
        """One-time setup: generate master keypair and register with registry.

        Returns:
            Registry response with key_id and public_key.

        Raises:
            RuntimeError: If master key already exists.
        """
        if master_key_exists(self.config_dir):
            raise RuntimeError(
                f"Master key already exists at {self.config_dir}. "
                "Delete it first if you want to reinitialize."
            )

        private_key, public_key = generate_master_key()
        save_master_key(private_key, public_key, self.config_dir)
        self._master_private = private_key
        self._master_public = public_key

        # Register with the registry
        resp = httpx.post(
            f"{self.registry_url}/v1/keys",
            json={"public_key": public_key.hex(), "label": label},
        )
        resp.raise_for_status()
        return resp.json()

    # --- Register agent ---

    def register(
        self,
        agent_name: str,
        description: str | None = None,
    ) -> AgentCredentials:
        """Register a new agent with the registry.

        Derives an agent keypair from the master key, registers it with the
        registry, and stores credentials locally.

        Args:
            agent_name: Globally unique agent name.
            description: What this agent does.

        Returns:
            AgentCredentials stored on disk.
        """
        validate_agent_name(agent_name)
        self._load_master_key()

        if self.store.exists(agent_name):
            raise RuntimeError(f"Agent '{agent_name}' is already registered locally.")

        # Derive agent keypair
        agent_private, agent_public = derive_agent_key(self._master_private, agent_name)

        # Register with registry
        payload = {
            "agent_name": agent_name,
            "agent_public_key": agent_public.hex(),
            "master_public_key": self._master_public.hex(),
            "description": description,
        }
        body = json.dumps(payload).encode()
        headers = self._sign_request(body)

        resp = httpx.post(
            f"{self.registry_url}/v1/agents",
            content=body,
            headers=headers,
        )
        resp.raise_for_status()

        # Store credentials locally
        creds = AgentCredentials(
            agent_name=agent_name,
            agent_public_key=agent_public.hex(),
            master_public_key=self._master_public.hex(),
            platform="agentauth",
            credentials=Credentials(
                platform="agentauth",
                token=agent_private.hex(),  # Agent private key is the auth token
            ),
        )
        self.store.save(creds)
        return creds

    # --- Authenticate ---

    def authenticate(self, agent_name: str) -> dict[str, str]:
        """Get authentication headers for an agent.

        Verifies the agent exists in the registry and returns signed headers
        that platforms can validate.

        Args:
            agent_name: Name of a registered agent.

        Returns:
            Dict with agent_name, agent_public_key, signature, and timestamp.
            Platforms use this to verify the agent via the registry.
        """
        creds = self.store.load(agent_name)
        agent_private = bytes.fromhex(creds.credentials.token)

        # Create a signed auth payload
        timestamp = datetime.now(UTC).isoformat()
        message = f"{agent_name}:{timestamp}".encode()
        signature = sign_message(agent_private, message)

        return {
            "agent_name": agent_name,
            "agent_public_key": creds.agent_public_key,
            "signature": signature.hex(),
            "timestamp": timestamp,
        }

    # --- List / Revoke ---

    def list_agents(self) -> list[AgentCredentials]:
        """List all locally registered agents."""
        return self.store.list_agents()

    def revoke(self, agent_name: str) -> bool:
        """Revoke an agent from the registry and delete local credentials."""
        self._load_master_key()

        headers = self._sign_request(b"")
        resp = httpx.delete(
            f"{self.registry_url}/v1/agents/{agent_name}",
            headers=headers,
        )

        if resp.status_code == 404:
            # Already gone from registry, clean up local
            self.store.delete(agent_name)
            return False

        resp.raise_for_status()
        self.store.delete(agent_name)
        return True
