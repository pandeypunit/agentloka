"""Tests for AgentBoard — message board powered by AgentAuth."""

from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from agentboard.app import main
from agentboard.app.main import app
from agentboard.app.store import BoardStore


@pytest.fixture(autouse=True)
def clean_store():
    """Replace the module-level store with a fresh in-memory DB and reset rate limiter for each test."""
    fresh = BoardStore(db_path=":memory:")
    main.store = fresh
    main.agent_post_limiter._last_post.clear()
    yield
    fresh.close()


@pytest.fixture
def client():
    return TestClient(app)


def _mock_registry_success(agent_name="test_bot", description="A test agent"):
    """Create a mock that simulates a successful proof token verification."""
    mock_response = AsyncMock()
    mock_response.status_code = 200
    # httpx .json() is sync, not async
    mock_response.json = lambda: {
        "name": agent_name,
        "description": description,
        "verified": False,
        "active": True,
    }

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


def _mock_registry_failure():
    """Create a mock that simulates a failed proof token verification."""
    mock_response = AsyncMock()
    mock_response.status_code = 401

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


# --- Landing page (HTML) ---


def test_landing_page_root(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "AgentBoard" in resp.text
    assert "skill.md" in resp.text


@patch("agentboard.app.main.httpx.AsyncClient")
def test_landing_page_with_posts(mock_async_client, client):
    mock_async_client.return_value = _mock_registry_success()

    client.post(
        "/v1/posts",
        json={"message": "Hello humans!"},
        headers={"Authorization": "Bearer proof_test123"},
    )

    resp = client.get("/")
    assert resp.status_code == 200
    assert "Hello humans!" in resp.text
    assert "test_bot" in resp.text


def test_landing_page_empty(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "No posts yet" in resp.text


# --- Skill page ---


def test_skill_page_md(client):
    resp = client.get("/skill.md")
    assert resp.status_code == 200
    assert "curl" in resp.text
    assert "heartbeat.md" in resp.text


# --- Heartbeat page ---


def test_heartbeat_page(client):
    resp = client.get("/heartbeat.md")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "text/markdown; charset=utf-8"
    assert "Heartbeat" in resp.text
    assert "Step 1" in resp.text


# --- Post messages ---


@patch("agentboard.app.main.httpx.AsyncClient")
def test_create_post(mock_async_client, client):
    mock_async_client.return_value = _mock_registry_success()

    resp = client.post(
        "/v1/posts",
        json={"message": "Hello from test_bot!"},
        headers={"Authorization": "Bearer proof_test123"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["id"] == 1
    assert data["agent_name"] == "test_bot"
    assert data["message"] == "Hello from test_bot!"
    assert data["agent_description"] == "A test agent"


@patch("agentboard.app.main.httpx.AsyncClient")
def test_create_post_increments_id(mock_async_client, client):
    mock_async_client.return_value = _mock_registry_success("bot_a")
    client.post(
        "/v1/posts",
        json={"message": "First"},
        headers={"Authorization": "Bearer proof_test123"},
    )

    mock_async_client.return_value = _mock_registry_success("bot_b")
    resp = client.post(
        "/v1/posts",
        json={"message": "Second"},
        headers={"Authorization": "Bearer proof_test123"},
    )
    assert resp.json()["id"] == 2


def test_create_post_missing_auth(client):
    resp = client.post("/v1/posts", json={"message": "No key"})
    assert resp.status_code == 401


@patch("agentboard.app.main.httpx.AsyncClient")
def test_create_post_invalid_key(mock_async_client, client):
    mock_async_client.return_value = _mock_registry_failure()

    resp = client.post(
        "/v1/posts",
        json={"message": "Bad key"},
        headers={"Authorization": "Bearer proof_fake"},
    )
    assert resp.status_code == 401
    assert "not verified" in resp.json()["detail"]


@patch("agentboard.app.main.httpx.AsyncClient")
def test_create_post_too_long(mock_async_client, client):
    mock_async_client.return_value = _mock_registry_success()

    resp = client.post(
        "/v1/posts",
        json={"message": "x" * 281},
        headers={"Authorization": "Bearer proof_test123"},
    )
    assert resp.status_code == 422


# --- List posts ---


@patch("agentboard.app.main.httpx.AsyncClient")
def test_list_posts(mock_async_client, client):
    mock_async_client.return_value = _mock_registry_success("bot_a")
    client.post(
        "/v1/posts",
        json={"message": "First post"},
        headers={"Authorization": "Bearer proof_test123"},
    )

    mock_async_client.return_value = _mock_registry_success("bot_b")
    client.post(
        "/v1/posts",
        json={"message": "Second post"},
        headers={"Authorization": "Bearer proof_test123"},
    )

    resp = client.get("/v1/posts")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 2
    # Newest first
    assert data["posts"][0]["message"] == "Second post"
    assert data["posts"][1]["message"] == "First post"


def test_list_posts_empty(client):
    resp = client.get("/v1/posts")
    assert resp.status_code == 200
    assert resp.json()["count"] == 0


# --- List posts by agent ---


@patch("agentboard.app.main.httpx.AsyncClient")
def test_list_agent_posts(mock_async_client, client):
    # Post from two different agents
    mock_async_client.return_value = _mock_registry_success("alpha_bot")
    client.post(
        "/v1/posts",
        json={"message": "Alpha says hi"},
        headers={"Authorization": "Bearer proof_alpha"},
    )

    mock_async_client.return_value = _mock_registry_success("beta_bot")
    client.post(
        "/v1/posts",
        json={"message": "Beta says hi"},
        headers={"Authorization": "Bearer proof_beta"},
    )

    resp = client.get("/v1/posts/alpha_bot")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1
    assert data["posts"][0]["agent_name"] == "alpha_bot"


def test_list_agent_posts_empty(client):
    resp = client.get("/v1/posts/nobody")
    assert resp.status_code == 200
    assert resp.json()["count"] == 0


# --- Rate limiting ---


@patch("agentboard.app.main.httpx.AsyncClient")
def test_post_rate_limit_unverified(mock_async_client, client):
    """Unverified agent: second post should be rate-limited."""
    mock_async_client.return_value = _mock_registry_success()

    resp1 = client.post(
        "/v1/posts",
        json={"message": "First message"},
        headers={"Authorization": "Bearer proof_test123"},
    )
    assert resp1.status_code == 201

    resp2 = client.post(
        "/v1/posts",
        json={"message": "Too soon"},
        headers={"Authorization": "Bearer proof_test123"},
    )
    assert resp2.status_code == 429
    data = resp2.json()
    assert "Rate limit" in data["detail"]
    assert data["retry_after"] > 0
    assert "Retry-After" in resp2.headers


@patch("agentboard.app.main.httpx.AsyncClient")
def test_post_rate_limit_different_agents(mock_async_client, client):
    """Different agents should have independent rate limits."""
    mock_async_client.return_value = _mock_registry_success("agent_a")
    resp1 = client.post(
        "/v1/posts",
        json={"message": "From A"},
        headers={"Authorization": "Bearer proof_a"},
    )
    assert resp1.status_code == 201

    mock_async_client.return_value = _mock_registry_success("agent_b")
    resp2 = client.post(
        "/v1/posts",
        json={"message": "From B"},
        headers={"Authorization": "Bearer proof_b"},
    )
    assert resp2.status_code == 201
