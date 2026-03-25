"""Tests for the AgentAuth registry API — flat identity model."""

import pytest
from fastapi.testclient import TestClient

from registry.app.main import app
from registry.app.store import RegistryStore, registry_store


@pytest.fixture(autouse=True)
def clean_store():
    """Give each test a fresh in-memory database."""
    import registry.app.store as store_module
    import registry.app.auth as auth_module
    import registry.app.main as main_module

    fresh = RegistryStore(db_path=":memory:")
    store_module.registry_store = fresh
    auth_module.registry_store = fresh
    main_module.registry_store = fresh
    yield
    return fresh


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def store():
    """Return the current test's store instance."""
    import registry.app.store as store_module
    return store_module.registry_store


def _register(client, name="test_bot", description="A test agent", email=None):
    payload = {"name": name, "description": description}
    if email is not None:
        payload["email"] = email
    return client.post("/v1/agents/register", json=payload)


def _api_key(resp):
    """Extract registry_secret_key from registration response."""
    return resp.json()["registry_secret_key"]


# --- Registration ---


def test_register_agent(client):
    resp = _register(client)
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "test_bot"
    assert data["registry_secret_key"].startswith("agentauth_")
    assert data["platform_proof_token"]  # JWT included
    assert data["platform_proof_token_expires_in_seconds"] == 300
    assert data["active"] is True
    assert data["verified"] is False
    assert data["description"] == "A test agent"
    assert data["important"] is not None
    assert "SAVE" in data["important"]
    assert "NEVER" in data["important"]


def test_register_proof_token_works_immediately(client):
    """Agent can use the proof token from registration without an extra call."""
    resp = _register(client)
    proof_token = resp.json()["platform_proof_token"]

    verify_resp = client.get(f"/v1/verify-proof/{proof_token}")
    assert verify_resp.status_code == 200
    assert verify_resp.json()["name"] == "test_bot"


def test_register_without_description(client):
    resp = client.post("/v1/agents/register", json={"name": "minimal_bot"})
    assert resp.status_code == 201
    assert resp.json()["description"] is None


def test_register_duplicate_name(client):
    _register(client, "taken_bot")
    resp = _register(client, "taken_bot")
    assert resp.status_code == 409


def test_register_invalid_name_uppercase(client):
    resp = _register(client, "BadName")
    assert resp.status_code == 422


def test_register_invalid_name_too_short(client):
    resp = _register(client, "a")
    assert resp.status_code == 422


def test_register_invalid_name_starts_with_number(client):
    resp = _register(client, "1bot")
    assert resp.status_code == 422


def test_register_invalid_name_hyphen(client):
    resp = _register(client, "my-bot")
    assert resp.status_code == 422


# --- Email Verification ---


def test_register_with_email_not_verified_yet(client, store):
    resp = _register(client, "email_bot", email="bot@example.com")
    assert resp.status_code == 201
    data = resp.json()
    assert data["verified"] is False
    assert store.count_pending_verifications() == 1


def test_verify_email(client, store):
    _register(client, "verify_bot", email="verify@example.com")

    token = store.get_pending_verification_token("verify_bot")
    assert token is not None

    resp = client.get(f"/v1/verify/{token}")
    assert resp.status_code == 200
    assert "verify_bot" in resp.text

    agent = client.get("/v1/agents/verify_bot").json()
    assert agent["verified"] is True

    assert store.get_verified_email("verify_bot") == "verify@example.com"
    assert store.count_pending_verifications() == 0


def test_verify_invalid_token(client):
    resp = client.get("/v1/verify/bogus_token")
    assert resp.status_code == 404


def test_verify_token_consumed_once(client, store):
    _register(client, "once_bot", email="once@example.com")
    token = store.get_pending_verification_token("once_bot")

    resp1 = client.get(f"/v1/verify/{token}")
    assert resp1.status_code == 200

    resp2 = client.get(f"/v1/verify/{token}")
    assert resp2.status_code == 404


def test_register_without_email_no_pending(client, store):
    _register(client, "no_email_bot")
    assert store.count_pending_verifications() == 0


def test_email_not_exposed_publicly(client, store):
    _register(client, "private_bot", email="private@example.com")
    token = store.get_pending_verification_token("private_bot")
    client.get(f"/v1/verify/{token}")

    agent = client.get("/v1/agents/private_bot").json()
    assert "email" not in agent


def test_verified_status_in_list(client, store):
    _register(client, "unverified_bot")
    _register(client, "verified_bot", email="v@example.com")
    token = store.get_pending_verification_token("verified_bot")
    client.get(f"/v1/verify/{token}")

    resp = client.get("/v1/agents")
    agents = {a["name"]: a for a in resp.json()["agents"]}
    assert agents["unverified_bot"]["verified"] is False
    assert agents["verified_bot"]["verified"] is True


# --- Link email (post-registration) ---


def test_link_email_after_registration(client, store):
    resp = _register(client, "late_email_bot")
    api_key = _api_key(resp)

    assert client.get("/v1/agents/late_email_bot").json()["verified"] is False

    link_resp = client.post(
        "/v1/agents/me/email",
        json={"email": "late@example.com"},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert link_resp.status_code == 200
    assert link_resp.json()["agent_name"] == "late_email_bot"

    token = store.get_pending_verification_token("late_email_bot")
    client.get(f"/v1/verify/{token}")

    agent = client.get("/v1/agents/late_email_bot").json()
    assert agent["verified"] is True
    assert store.get_verified_email("late_email_bot") == "late@example.com"


def test_link_email_missing_auth(client):
    resp = client.post("/v1/agents/me/email", json={"email": "x@example.com"})
    assert resp.status_code == 401


def test_link_email_invalid_key(client):
    resp = client.post(
        "/v1/agents/me/email",
        json={"email": "x@example.com"},
        headers={"Authorization": "Bearer agentauth_fake"},
    )
    assert resp.status_code == 401


# --- Lookup ---


def test_get_agent(client):
    _register(client, "lookup_bot")
    resp = client.get("/v1/agents/lookup_bot")
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "lookup_bot"
    assert data["registry_secret_key"] is None  # Never exposed on public lookup


def test_get_agent_not_found(client):
    resp = client.get("/v1/agents/ghost_bot")
    assert resp.status_code == 404


def test_list_agents(client):
    _register(client, "alpha_bot")
    _register(client, "beta_bot")
    resp = client.get("/v1/agents")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 2
    names = {a["name"] for a in data["agents"]}
    assert names == {"alpha_bot", "beta_bot"}
    for agent in data["agents"]:
        assert agent["registry_secret_key"] is None


# --- Identity Verification ---


def test_get_me(client):
    resp = _register(client)
    api_key = _api_key(resp)

    me_resp = client.get("/v1/agents/me", headers={"Authorization": f"Bearer {api_key}"})
    assert me_resp.status_code == 200
    assert me_resp.json()["name"] == "test_bot"


def test_get_me_invalid_key(client):
    resp = client.get("/v1/agents/me", headers={"Authorization": "Bearer agentauth_fake"})
    assert resp.status_code == 401


def test_get_me_missing_header(client):
    resp = client.get("/v1/agents/me")
    assert resp.status_code == 401


# --- Revocation ---


def test_revoke_agent(client):
    resp = _register(client, "doomed_bot")
    api_key = _api_key(resp)

    del_resp = client.delete("/v1/agents/doomed_bot", headers={"Authorization": f"Bearer {api_key}"})
    assert del_resp.status_code == 200
    assert del_resp.json()["revoked"] is True

    assert client.get("/v1/agents/doomed_bot").status_code == 404


def test_revoke_wrong_key(client):
    _register(client, "protected_bot")
    resp = client.delete("/v1/agents/protected_bot", headers={"Authorization": "Bearer agentauth_wrong"})
    assert resp.status_code == 403


def test_revoke_missing_auth(client):
    _register(client, "safe_bot")
    resp = client.delete("/v1/agents/safe_bot")
    assert resp.status_code == 401


def test_revoke_cleans_up_email(client, store):
    resp = _register(client, "cleanup_bot", email="cleanup@example.com")
    api_key = _api_key(resp)
    token = store.get_pending_verification_token("cleanup_bot")
    client.get(f"/v1/verify/{token}")
    assert store.get_verified_email("cleanup_bot") == "cleanup@example.com"

    client.delete("/v1/agents/cleanup_bot", headers={"Authorization": f"Bearer {api_key}"})
    assert store.get_verified_email("cleanup_bot") is None


# --- Proof tokens (JWT) ---


def test_create_proof_token(client):
    resp = _register(client)
    api_key = _api_key(resp)

    proof_resp = client.post("/v1/agents/me/proof", headers={"Authorization": f"Bearer {api_key}"})
    assert proof_resp.status_code == 200
    data = proof_resp.json()
    assert data["platform_proof_token"]  # JWT string
    assert data["agent_name"] == "test_bot"
    assert data["expires_in_seconds"] == 300


def test_verify_proof_token(client):
    resp = _register(client)
    api_key = _api_key(resp)

    proof_resp = client.post("/v1/agents/me/proof", headers={"Authorization": f"Bearer {api_key}"})
    proof_token = proof_resp.json()["platform_proof_token"]

    verify_resp = client.get(f"/v1/verify-proof/{proof_token}")
    assert verify_resp.status_code == 200
    data = verify_resp.json()
    assert data["name"] == "test_bot"
    assert data["active"] is True


def test_proof_token_reusable(client):
    resp = _register(client)
    api_key = _api_key(resp)

    proof_resp = client.post("/v1/agents/me/proof", headers={"Authorization": f"Bearer {api_key}"})
    proof_token = proof_resp.json()["platform_proof_token"]

    assert client.get(f"/v1/verify-proof/{proof_token}").status_code == 200
    assert client.get(f"/v1/verify-proof/{proof_token}").status_code == 200


def test_proof_token_invalid(client):
    resp = client.get("/v1/verify-proof/bogus_token")
    assert resp.status_code == 401


def test_proof_token_missing_auth(client):
    resp = client.post("/v1/agents/me/proof")
    assert resp.status_code == 401


def test_proof_token_expired(client, store):
    import jwt as pyjwt

    _register(client)

    expired_payload = {
        "sub": "test_bot",
        "description": "A test agent",
        "verified": False,
        "iat": 1000000,
        "exp": 1000001,
    }
    expired_token = pyjwt.encode(expired_payload, store._signing_key, algorithm="ES256")

    assert client.get(f"/v1/verify-proof/{expired_token}").status_code == 401


def test_proof_token_after_agent_revoked(client):
    resp = _register(client)
    api_key = _api_key(resp)

    proof_resp = client.post("/v1/agents/me/proof", headers={"Authorization": f"Bearer {api_key}"})
    proof_token = proof_resp.json()["platform_proof_token"]

    client.delete("/v1/agents/test_bot", headers={"Authorization": f"Bearer {api_key}"})

    assert client.get(f"/v1/verify-proof/{proof_token}").status_code == 401


def test_jwks_endpoint(client):
    resp = client.get("/.well-known/jwks.json")
    assert resp.status_code == 200
    data = resp.json()
    assert "public_key_pem" in data
    assert "BEGIN PUBLIC KEY" in data["public_key_pem"]


def test_verify_proof_locally_with_public_key(client):
    import jwt as pyjwt

    resp = _register(client)

    proof_token = resp.json()["platform_proof_token"]

    jwks_resp = client.get("/.well-known/jwks.json")
    public_key_pem = jwks_resp.json()["public_key_pem"]

    payload = pyjwt.decode(proof_token, public_key_pem, algorithms=["ES256"])
    assert payload["sub"] == "test_bot"
    assert "exp" in payload


# --- Skill page ---


def test_skill_page_root(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "text/markdown; charset=utf-8"
    assert "AgentAuth" in resp.text


def test_skill_page_md(client):
    resp = client.get("/skill.md")
    assert resp.status_code == 200
    assert "curl" in resp.text
