"""In-memory store for the registry. Replace with a database for production."""

from datetime import UTC, datetime
import hashlib

from registry.app.models import KeyResponse, AgentResponse


class RegistryStore:
    """In-memory store for master keys and agents. Good enough for v0.1."""

    def __init__(self):
        self._keys: dict[str, KeyResponse] = {}          # key_id -> KeyResponse
        self._keys_by_pub: dict[str, str] = {}            # public_key hex -> key_id
        self._agents: dict[str, AgentResponse] = {}       # agent_name -> AgentResponse
        self._agents_by_master: dict[str, list[str]] = {} # master pub hex -> [agent_names]

    @staticmethod
    def _make_key_id(public_key: str) -> str:
        return "k_" + hashlib.sha256(bytes.fromhex(public_key)).hexdigest()[:12]

    # --- Keys ---

    def register_key(self, public_key: str, label: str) -> KeyResponse:
        if public_key in self._keys_by_pub:
            return None  # Already exists

        key_id = self._make_key_id(public_key)
        record = KeyResponse(
            key_id=key_id,
            public_key=public_key,
            label=label,
            created_at=datetime.now(UTC),
            agent_count=0,
        )
        self._keys[key_id] = record
        self._keys_by_pub[public_key] = key_id
        self._agents_by_master[public_key] = []
        return record

    def get_key_by_id(self, key_id: str) -> KeyResponse | None:
        record = self._keys.get(key_id)
        if record:
            record.agent_count = len(self._agents_by_master.get(record.public_key, []))
        return record

    def get_key_by_public_key(self, public_key: str) -> KeyResponse | None:
        key_id = self._keys_by_pub.get(public_key)
        if key_id:
            return self.get_key_by_id(key_id)
        return None

    def revoke_key(self, key_id: str) -> int:
        """Revoke a key and all its agents. Returns count of agents revoked."""
        record = self._keys.pop(key_id, None)
        if not record:
            return -1

        self._keys_by_pub.pop(record.public_key, None)
        agent_names = self._agents_by_master.pop(record.public_key, [])
        for name in agent_names:
            self._agents.pop(name, None)
        return len(agent_names)

    # --- Agents ---

    def register_agent(
        self, agent_name: str, agent_public_key: str,
        master_public_key: str, description: str | None,
    ) -> AgentResponse | None:
        if agent_name in self._agents:
            return None  # Name taken

        if master_public_key not in self._keys_by_pub:
            raise LookupError("Master key not registered")

        record = AgentResponse(
            agent_name=agent_name,
            agent_public_key=agent_public_key,
            master_public_key=master_public_key,
            description=description,
            created_at=datetime.now(UTC),
            active=True,
        )
        self._agents[agent_name] = record
        self._agents_by_master[master_public_key].append(agent_name)
        return record

    def get_agent(self, agent_name: str) -> AgentResponse | None:
        return self._agents.get(agent_name)

    def list_agents_by_master(self, master_public_key: str) -> list[AgentResponse]:
        names = self._agents_by_master.get(master_public_key, [])
        return [self._agents[n] for n in names if n in self._agents]

    def revoke_agent(self, agent_name: str, master_public_key: str) -> bool:
        agent = self._agents.get(agent_name)
        if not agent or agent.master_public_key != master_public_key:
            return False
        self._agents.pop(agent_name)
        if agent_name in self._agents_by_master.get(master_public_key, []):
            self._agents_by_master[master_public_key].remove(agent_name)
        return True


# Singleton for the app
registry_store = RegistryStore()
