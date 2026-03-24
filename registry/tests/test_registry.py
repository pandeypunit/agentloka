"""Tests for the AgentAuth registry API — flat identity model."""

import pytest
from fastapi.testclient import TestClient

from registry.app.main import app
from registry.app.store import registry_store


@pytest.fixture(autouse=True)
def clean_store():
    registry_store._agents.clear()
    registry_store._keys.clear()
    yield


@pytest.fixture
def client():
    return TestClient(app)


def _register(client, name="test_bot", description="A test agent"):
    return client.post("/v1/agents/register", json={"name": name, "description": description})


# --- Registration ---


def test_register_agent(client):
    resp = _register(client)
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "test_bot"
    assert data["api_key"].startswith("agentauth_")
    assert data["active"] is True
    assert data["description"] == "A test agent"


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


# --- Lookup ---


def test_get_agent(client):
    _register(client, "lookup_bot")
    resp = client.get("/v1/agents/lookup_bot")
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "lookup_bot"
    assert data["api_key"] is None  # Never exposed on public lookup


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
    # API keys never exposed
    for agent in data["agents"]:
        assert agent["api_key"] is None


# --- Identity Verification ---


def test_get_me(client):
    resp = _register(client)
    api_key = resp.json()["api_key"]

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
    api_key = resp.json()["api_key"]

    del_resp = client.delete("/v1/agents/doomed_bot", headers={"Authorization": f"Bearer {api_key}"})
    assert del_resp.status_code == 200
    assert del_resp.json()["revoked"] is True

    # Should be gone
    assert client.get("/v1/agents/doomed_bot").status_code == 404


def test_revoke_wrong_key(client):
    _register(client, "protected_bot")
    resp = client.delete("/v1/agents/protected_bot", headers={"Authorization": "Bearer agentauth_wrong"})
    assert resp.status_code == 403


def test_revoke_missing_auth(client):
    _register(client, "safe_bot")
    resp = client.delete("/v1/agents/safe_bot")
    assert resp.status_code == 401


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
