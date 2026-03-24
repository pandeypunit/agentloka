"""Tests for the AgentAuth registry API."""

from datetime import UTC, datetime

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)
from fastapi.testclient import TestClient

from registry.app.main import app
from registry.app.store import registry_store


@pytest.fixture(autouse=True)
def clean_store():
    """Reset the registry store between tests."""
    registry_store._keys.clear()
    registry_store._keys_by_pub.clear()
    registry_store._agents.clear()
    registry_store._agents_by_master.clear()
    yield


@pytest.fixture
def client():
    return TestClient(app)


def _generate_keypair() -> tuple[bytes, bytes]:
    private_key = Ed25519PrivateKey.generate()
    private_bytes = private_key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    public_bytes = private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return private_bytes, public_bytes


def _sign_request(private_key_bytes: bytes, body: bytes) -> dict:
    """Create auth headers for a signed request."""
    timestamp = datetime.now(UTC).isoformat()
    message = f"{timestamp}\n".encode() + body
    private_key = Ed25519PrivateKey.from_private_bytes(private_key_bytes)
    signature = private_key.sign(message)
    public_bytes = private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return {
        "X-AgentAuth-PublicKey": public_bytes.hex(),
        "X-AgentAuth-Signature": signature.hex(),
        "X-AgentAuth-Timestamp": timestamp,
    }


# --- Key endpoints ---


def test_register_key(client):
    _, public_key = _generate_keypair()
    resp = client.post("/v1/keys", json={"public_key": public_key.hex(), "label": "test"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["public_key"] == public_key.hex()
    assert data["key_id"].startswith("k_")
    assert data["label"] == "test"


def test_register_key_duplicate(client):
    _, public_key = _generate_keypair()
    client.post("/v1/keys", json={"public_key": public_key.hex()})
    resp = client.post("/v1/keys", json={"public_key": public_key.hex()})
    assert resp.status_code == 409


def test_register_key_invalid_format(client):
    resp = client.post("/v1/keys", json={"public_key": "not_hex"})
    assert resp.status_code == 422


def test_get_key_by_id(client):
    _, public_key = _generate_keypair()
    create_resp = client.post("/v1/keys", json={"public_key": public_key.hex()})
    key_id = create_resp.json()["key_id"]

    resp = client.get(f"/v1/keys/{key_id}")
    assert resp.status_code == 200
    assert resp.json()["public_key"] == public_key.hex()


def test_get_key_by_public_key(client):
    _, public_key = _generate_keypair()
    client.post("/v1/keys", json={"public_key": public_key.hex()})

    resp = client.get(f"/v1/keys?public_key={public_key.hex()}")
    assert resp.status_code == 200
    assert resp.json()["public_key"] == public_key.hex()


def test_get_key_not_found(client):
    resp = client.get("/v1/keys/k_nonexistent")
    assert resp.status_code == 404


def test_revoke_key(client):
    private_key, public_key = _generate_keypair()
    create_resp = client.post("/v1/keys", json={"public_key": public_key.hex()})
    key_id = create_resp.json()["key_id"]

    headers = _sign_request(private_key, b"")
    resp = client.delete(f"/v1/keys/{key_id}", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["revoked"] is True

    # Key should be gone
    assert client.get(f"/v1/keys/{key_id}").status_code == 404


# --- Agent endpoints ---


def test_register_agent(client):
    private_key, public_key = _generate_keypair()
    client.post("/v1/keys", json={"public_key": public_key.hex()})

    import json as json_lib

    body = json_lib.dumps({
        "agent_name": "test_bot",
        "agent_public_key": "aa" * 32,
        "master_public_key": public_key.hex(),
        "description": "A test agent",
    }).encode()

    headers = _sign_request(private_key, body)
    headers["Content-Type"] = "application/json"
    resp = client.post("/v1/agents", content=body, headers=headers)
    assert resp.status_code == 201
    data = resp.json()
    assert data["agent_name"] == "test_bot"
    assert data["active"] is True


def test_register_agent_duplicate_name(client):
    private_key, public_key = _generate_keypair()
    client.post("/v1/keys", json={"public_key": public_key.hex()})

    import json as json_lib

    body = json_lib.dumps({
        "agent_name": "taken_bot",
        "agent_public_key": "aa" * 32,
        "master_public_key": public_key.hex(),
    }).encode()

    headers = _sign_request(private_key, body)
    headers["Content-Type"] = "application/json"
    client.post("/v1/agents", content=body, headers=headers)

    # Second registration with same name — new body/signature needed
    body2 = json_lib.dumps({
        "agent_name": "taken_bot",
        "agent_public_key": "bb" * 32,
        "master_public_key": public_key.hex(),
    }).encode()
    headers2 = _sign_request(private_key, body2)
    headers2["Content-Type"] = "application/json"
    resp = client.post("/v1/agents", content=body2, headers=headers2)
    assert resp.status_code == 409


def test_register_agent_unregistered_master(client):
    private_key, public_key = _generate_keypair()

    import json as json_lib

    body = json_lib.dumps({
        "agent_name": "orphan_bot",
        "agent_public_key": "aa" * 32,
        "master_public_key": public_key.hex(),
    }).encode()

    headers = _sign_request(private_key, body)
    headers["Content-Type"] = "application/json"
    resp = client.post("/v1/agents", content=body, headers=headers)
    assert resp.status_code == 404


def test_register_agent_wrong_signer(client):
    _, public_key = _generate_keypair()
    other_private, _ = _generate_keypair()
    client.post("/v1/keys", json={"public_key": public_key.hex()})

    import json as json_lib

    body = json_lib.dumps({
        "agent_name": "sneaky_bot",
        "agent_public_key": "aa" * 32,
        "master_public_key": public_key.hex(),
    }).encode()

    # Sign with wrong key
    headers = _sign_request(other_private, body)
    headers["Content-Type"] = "application/json"
    resp = client.post("/v1/agents", content=body, headers=headers)
    assert resp.status_code == 403


def test_get_agent(client):
    private_key, public_key = _generate_keypair()
    client.post("/v1/keys", json={"public_key": public_key.hex()})

    import json as json_lib

    body = json_lib.dumps({
        "agent_name": "lookup_bot",
        "agent_public_key": "cc" * 32,
        "master_public_key": public_key.hex(),
    }).encode()
    headers = _sign_request(private_key, body)
    headers["Content-Type"] = "application/json"
    client.post("/v1/agents", content=body, headers=headers)

    resp = client.get("/v1/agents/lookup_bot")
    assert resp.status_code == 200
    assert resp.json()["agent_name"] == "lookup_bot"


def test_get_agent_not_found(client):
    resp = client.get("/v1/agents/ghost_bot")
    assert resp.status_code == 404


def test_list_agents_by_master(client):
    private_key, public_key = _generate_keypair()
    client.post("/v1/keys", json={"public_key": public_key.hex()})

    import json as json_lib

    for name in ["alpha_bot", "beta_bot"]:
        body = json_lib.dumps({
            "agent_name": name,
            "agent_public_key": "dd" * 32,
            "master_public_key": public_key.hex(),
        }).encode()
        headers = _sign_request(private_key, body)
        headers["Content-Type"] = "application/json"
        client.post("/v1/agents", content=body, headers=headers)

    resp = client.get(f"/v1/agents?master_public_key={public_key.hex()}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 2


def test_revoke_agent(client):
    private_key, public_key = _generate_keypair()
    client.post("/v1/keys", json={"public_key": public_key.hex()})

    import json as json_lib

    body = json_lib.dumps({
        "agent_name": "doomed_bot",
        "agent_public_key": "ee" * 32,
        "master_public_key": public_key.hex(),
    }).encode()
    headers = _sign_request(private_key, body)
    headers["Content-Type"] = "application/json"
    client.post("/v1/agents", content=body, headers=headers)

    del_headers = _sign_request(private_key, b"")
    resp = client.delete("/v1/agents/doomed_bot", headers=del_headers)
    assert resp.status_code == 200
    assert resp.json()["revoked"] is True

    # Should be gone
    assert client.get("/v1/agents/doomed_bot").status_code == 404


def test_revoke_key_cascades_to_agents(client):
    private_key, public_key = _generate_keypair()
    create_resp = client.post("/v1/keys", json={"public_key": public_key.hex()})
    key_id = create_resp.json()["key_id"]

    import json as json_lib

    for name in ["cascade_a", "cascade_b"]:
        body = json_lib.dumps({
            "agent_name": name,
            "agent_public_key": "ff" * 32,
            "master_public_key": public_key.hex(),
        }).encode()
        headers = _sign_request(private_key, body)
        headers["Content-Type"] = "application/json"
        client.post("/v1/agents", content=body, headers=headers)

    del_headers = _sign_request(private_key, b"")
    resp = client.delete(f"/v1/keys/{key_id}", headers=del_headers)
    assert resp.json()["agents_revoked"] == 2

    # Both agents should be gone
    assert client.get("/v1/agents/cascade_a").status_code == 404
    assert client.get("/v1/agents/cascade_b").status_code == 404


def test_missing_auth_headers(client):
    resp = client.delete("/v1/keys/k_something")
    assert resp.status_code == 401
