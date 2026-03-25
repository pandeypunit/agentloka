"""In-memory store — flat identity, one API key per agent."""

import secrets
from datetime import UTC, datetime

import jwt
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PublicFormat,
    PrivateFormat,
)

from registry.app.models import AgentResponse

PROOF_TOKEN_TTL_SECONDS = 300  # 5 minutes — reusable until expiry


def _generate_signing_key() -> ec.EllipticCurvePrivateKey:
    """Generate an ECDSA P-256 signing key for JWT proof tokens."""
    return ec.generate_private_key(ec.SECP256R1())


class RegistryStore:
    """In-memory store for agents. Replace with a database for production."""

    def __init__(self):
        self._agents: dict[str, AgentResponse] = {}  # name -> AgentResponse
        self._keys: dict[str, str] = {}               # api_key -> agent name
        self._emails: dict[str, str] = {}             # agent name -> email (only after verification)
        self._pending_verifications: dict[str, dict] = {}  # token -> {"agent_name", "email"}
        self._signing_key = _generate_signing_key()

    @property
    def public_key_pem(self) -> str:
        """PEM-encoded public key for JWT verification."""
        return self._signing_key.public_key().public_bytes(
            Encoding.PEM, PublicFormat.SubjectPublicKeyInfo
        ).decode()

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
        proof_token = None
        agent = AgentResponse(
            name=name,
            description=description,
            registry_secret_key=api_key,
            verified=False,
            created_at=datetime.now(UTC),
            active=True,
        )
        self._agents[name] = agent
        self._keys[api_key] = name

        # Generate a proof token so agent can use platforms immediately
        proof_token = self.create_proof_token(name)
        agent = agent.model_copy(update={
            "platform_proof_token": proof_token,
            "platform_proof_token_expires_in_seconds": PROOF_TOKEN_TTL_SECONDS,
        })

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

    def create_proof_token(self, agent_name: str) -> str:
        """Create a JWT proof token for an agent. Reusable until expiry."""
        agent = self._agents.get(agent_name)
        now = datetime.now(UTC).timestamp()
        payload = {
            "sub": agent_name,
            "description": agent.description if agent else None,
            "verified": agent.verified if agent else False,
            "iat": int(now),
            "exp": int(now) + PROOF_TOKEN_TTL_SECONDS,
        }
        return jwt.encode(payload, self._signing_key, algorithm="ES256")

    def verify_proof_token(self, token: str) -> dict | None:
        """Verify a JWT proof token. Returns decoded payload or None."""
        try:
            payload = jwt.decode(
                token,
                self._signing_key.public_key(),
                algorithms=["ES256"],
            )
        except jwt.InvalidTokenError:
            return None
        # Check agent still exists
        agent_name = payload.get("sub")
        if agent_name not in self._agents:
            return None
        return payload

    def get_agent(self, name: str) -> AgentResponse | None:
        agent = self._agents.get(name)
        if agent:
            # Public lookup — strip secrets
            return agent.model_copy(update={"registry_secret_key": None})
        return None

    def get_agent_by_key(self, api_key: str) -> AgentResponse | None:
        name = self._keys.get(api_key)
        if name:
            return self._agents.get(name)
        return None

    def list_agents(self) -> list[AgentResponse]:
        # Public listing — strip secrets
        return [a.model_copy(update={"registry_secret_key": None}) for a in self._agents.values()]

    def revoke_agent(self, name: str, api_key: str) -> bool:
        """Revoke an agent. Must provide the correct API key."""
        agent = self._agents.get(name)
        if not agent or agent.registry_secret_key != api_key:
            return False
        self._agents.pop(name)
        self._keys.pop(api_key, None)
        self._emails.pop(name, None)
        return True


registry_store = RegistryStore()
