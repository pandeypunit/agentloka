"""Tests for core models and credential store."""

import tempfile
from pathlib import Path

import pytest
from agentauth.core.identity import AgentIdentity, validate_agent_name
from agentauth.core.credentials import Credentials, AgentCredentials
from agentauth.core.credential_store import CredentialStore


# --- AgentIdentity ---


def test_valid_agent_identity():
    agent = AgentIdentity(
        name="test_bot",
        description="A test agent",
        public_key="aa" * 32,
        master_public_key="bb" * 32,
    )
    assert agent.name == "test_bot"


def test_agent_name_validation_valid():
    for name in ["ab", "my_agent", "bot123", "a" * 32]:
        validate_agent_name(name)


def test_agent_name_validation_invalid():
    for name in ["", "a", "A", "1agent", "my-agent", "has space", "a" * 33, "UPPER"]:
        with pytest.raises(ValueError):
            validate_agent_name(name)


def test_agent_identity_rejects_bad_name():
    with pytest.raises(ValueError):
        AgentIdentity(
            name="BAD",
            public_key="aa" * 32,
            master_public_key="bb" * 32,
        )


# --- Credentials ---


def test_credentials_minimal():
    creds = Credentials(platform="moltbook", api_key="moltbook_abc123")
    assert creds.platform == "moltbook"
    assert creds.api_key == "moltbook_abc123"
    assert creds.token is None
    assert creds.expires_at is None


def test_agent_credentials_full():
    creds = AgentCredentials(
        agent_name="my_bot",
        agent_public_key="aa" * 32,
        master_public_key="bb" * 32,
        platform="test_platform",
        credentials=Credentials(platform="test_platform", api_key="key_123"),
    )
    assert creds.agent_name == "my_bot"
    assert creds.registered_at is not None


# --- CredentialStore ---


def test_store_save_and_load():
    with tempfile.TemporaryDirectory() as tmpdir:
        store = CredentialStore(config_dir=Path(tmpdir))
        creds = AgentCredentials(
            agent_name="my_bot",
            agent_public_key="aa" * 32,
            master_public_key="bb" * 32,
            platform="test",
            credentials=Credentials(platform="test", api_key="key_123"),
        )

        store.save(creds)
        loaded = store.load("my_bot")

        assert loaded.agent_name == "my_bot"
        assert loaded.credentials.api_key == "key_123"


def test_store_exists():
    with tempfile.TemporaryDirectory() as tmpdir:
        store = CredentialStore(config_dir=Path(tmpdir))
        assert not store.exists("ghost_bot")

        creds = AgentCredentials(
            agent_name="real_bot",
            agent_public_key="aa" * 32,
            master_public_key="bb" * 32,
            platform="test",
            credentials=Credentials(platform="test", api_key="k"),
        )
        store.save(creds)
        assert store.exists("real_bot")


def test_store_load_missing_raises():
    with tempfile.TemporaryDirectory() as tmpdir:
        store = CredentialStore(config_dir=Path(tmpdir))
        with pytest.raises(FileNotFoundError):
            store.load("nonexistent")


def test_store_list_agents():
    with tempfile.TemporaryDirectory() as tmpdir:
        store = CredentialStore(config_dir=Path(tmpdir))

        for name in ["alpha_bot", "beta_bot", "gamma_bot"]:
            store.save(
                AgentCredentials(
                    agent_name=name,
                    agent_public_key="aa" * 32,
                    master_public_key="bb" * 32,
                    platform="test",
                    credentials=Credentials(platform="test", api_key=f"key_{name}"),
                )
            )

        agents = store.list_agents()
        assert len(agents) == 3
        assert [a.agent_name for a in agents] == ["alpha_bot", "beta_bot", "gamma_bot"]


def test_store_delete():
    with tempfile.TemporaryDirectory() as tmpdir:
        store = CredentialStore(config_dir=Path(tmpdir))
        creds = AgentCredentials(
            agent_name="doomed_bot",
            agent_public_key="aa" * 32,
            master_public_key="bb" * 32,
            platform="test",
            credentials=Credentials(platform="test", api_key="k"),
        )
        store.save(creds)
        assert store.exists("doomed_bot")

        assert store.delete("doomed_bot") is True
        assert not store.exists("doomed_bot")
        assert store.delete("doomed_bot") is False
