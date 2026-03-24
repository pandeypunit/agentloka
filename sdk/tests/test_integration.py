"""Integration tests — full flow against a live registry."""

import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agentauth.client import AgentAuth
from registry.app.main import app
from registry.app.store import registry_store


@pytest.fixture(autouse=True)
def clean_store():
    registry_store._keys.clear()
    registry_store._keys_by_pub.clear()
    registry_store._agents.clear()
    registry_store._agents_by_master.clear()
    yield


@pytest.fixture
def tmp_config():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def test_client():
    """HTTPX-compatible test client for the registry."""
    return TestClient(app)


@pytest.fixture
def auth(tmp_config, test_client, monkeypatch):
    """AgentAuth instance wired to the test registry."""
    agent_auth = AgentAuth(
        registry_url="http://testserver",
        config_dir=tmp_config,
    )
    # Monkey-patch httpx to use the test client
    import httpx as _httpx

    original_post = _httpx.post
    original_delete = _httpx.delete
    original_get = _httpx.get

    def patched_post(url, **kwargs):
        path = url.replace("http://testserver", "")
        return test_client.post(path, **kwargs)

    def patched_delete(url, **kwargs):
        path = url.replace("http://testserver", "")
        return test_client.delete(path, **kwargs)

    def patched_get(url, **kwargs):
        path = url.replace("http://testserver", "")
        return test_client.get(path, **kwargs)

    monkeypatch.setattr(_httpx, "post", patched_post)
    monkeypatch.setattr(_httpx, "delete", patched_delete)
    monkeypatch.setattr(_httpx, "get", patched_get)

    return agent_auth


def test_full_flow(auth):
    """Init → register → authenticate → list → revoke."""
    # 1. Init — generate master key and register with registry
    result = auth.init(label="integration-test")
    assert result["key_id"].startswith("k_")
    assert result["public_key"]

    # 2. Register an agent
    creds = auth.register("test_bot", description="Integration test agent")
    assert creds.agent_name == "test_bot"
    assert creds.agent_public_key
    assert creds.master_public_key == result["public_key"]

    # 3. Authenticate — get signed auth payload
    token = auth.authenticate("test_bot")
    assert token["agent_name"] == "test_bot"
    assert token["agent_public_key"] == creds.agent_public_key
    assert token["signature"]
    assert token["timestamp"]

    # 4. List agents
    agents = auth.list_agents()
    assert len(agents) == 1
    assert agents[0].agent_name == "test_bot"

    # 5. Revoke
    revoked = auth.revoke("test_bot")
    assert revoked is True
    assert len(auth.list_agents()) == 0


def test_register_multiple_agents(auth):
    auth.init()
    auth.register("alpha_bot")
    auth.register("beta_bot")
    auth.register("gamma_bot")

    agents = auth.list_agents()
    assert len(agents) == 3
    names = {a.agent_name for a in agents}
    assert names == {"alpha_bot", "beta_bot", "gamma_bot"}


def test_register_duplicate_fails(auth):
    auth.init()
    auth.register("unique_bot")
    with pytest.raises(RuntimeError, match="already registered locally"):
        auth.register("unique_bot")


def test_init_twice_fails(auth):
    auth.init()
    with pytest.raises(RuntimeError, match="already exists"):
        auth.init()


def test_register_without_init_fails(auth):
    with pytest.raises(FileNotFoundError):
        auth.register("orphan_bot")


def test_authenticate_unregistered_fails(auth):
    auth.init()
    with pytest.raises(FileNotFoundError):
        auth.authenticate("ghost_bot")


def test_auth_signature_is_verifiable(auth):
    """Verify the auth payload can actually be verified cryptographically."""
    from agentauth.keys.derivation import verify_signature

    auth.init()
    auth.register("signer_bot")
    token = auth.authenticate("signer_bot")

    message = f"{token['agent_name']}:{token['timestamp']}".encode()
    public_key = bytes.fromhex(token["agent_public_key"])
    signature = bytes.fromhex(token["signature"])

    assert verify_signature(public_key, message, signature)
