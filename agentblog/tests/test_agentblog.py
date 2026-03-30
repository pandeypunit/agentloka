"""Tests for AgentBlog — blog platform powered by AgentAuth."""

from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from agentblog.app import main
from agentblog.app.main import app
from agentblog.app.store import BlogStore


@pytest.fixture(autouse=True)
def clean_store():
    """Replace the module-level store with a fresh in-memory DB and reset rate limiter for each test."""
    fresh = BlogStore(db_path=":memory:")
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
    assert "AgentBlog" in resp.text
    assert "skill.md" in resp.text


@patch("agentblog.app.main.httpx.AsyncClient")
def test_landing_page_with_posts(mock_async_client, client):
    mock_async_client.return_value = _mock_registry_success()

    client.post(
        "/v1/posts",
        json={"title": "Hello Humans", "body": "A post for the landing page", "category": "technology"},
        headers={"Authorization": "Bearer proof_test123"},
    )

    resp = client.get("/")
    assert resp.status_code == 200
    assert "Hello Humans" in resp.text
    assert "test_bot" in resp.text
    assert '/post/1"' in resp.text


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


# --- Create posts ---


@patch("agentblog.app.main.httpx.AsyncClient")
def test_create_post(mock_async_client, client):
    mock_async_client.return_value = _mock_registry_success()

    resp = client.post(
        "/v1/posts",
        json={
            "title": "My First Post",
            "body": "Hello from test_bot!",
            "category": "technology",
            "tags": ["ai", "testing"],
        },
        headers={"Authorization": "Bearer proof_test123"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["id"] == 1
    assert data["agent_name"] == "test_bot"
    assert data["title"] == "My First Post"
    assert data["body"] == "Hello from test_bot!"
    assert data["category"] == "technology"
    assert data["tags"] == ["ai", "testing"]
    assert data["agent_description"] == "A test agent"


def test_create_post_missing_auth(client):
    resp = client.post(
        "/v1/posts",
        json={"title": "No Auth", "body": "Test", "category": "technology"},
    )
    assert resp.status_code == 401


@patch("agentblog.app.main.httpx.AsyncClient")
def test_create_post_invalid_token(mock_async_client, client):
    mock_async_client.return_value = _mock_registry_failure()

    resp = client.post(
        "/v1/posts",
        json={"title": "Bad Token", "body": "Test", "category": "technology"},
        headers={"Authorization": "Bearer proof_fake"},
    )
    assert resp.status_code == 401
    assert "not verified" in resp.json()["detail"]


@patch("agentblog.app.main.httpx.AsyncClient")
def test_create_post_title_too_long(mock_async_client, client):
    mock_async_client.return_value = _mock_registry_success()

    resp = client.post(
        "/v1/posts",
        json={"title": "x" * 201, "body": "Test", "category": "technology"},
        headers={"Authorization": "Bearer proof_test123"},
    )
    assert resp.status_code == 422


@patch("agentblog.app.main.httpx.AsyncClient")
def test_create_post_body_too_long(mock_async_client, client):
    mock_async_client.return_value = _mock_registry_success()

    resp = client.post(
        "/v1/posts",
        json={"title": "Long Body", "body": "x" * 8001, "category": "technology"},
        headers={"Authorization": "Bearer proof_test123"},
    )
    assert resp.status_code == 422


@patch("agentblog.app.main.httpx.AsyncClient")
def test_create_post_invalid_category(mock_async_client, client):
    mock_async_client.return_value = _mock_registry_success()

    resp = client.post(
        "/v1/posts",
        json={"title": "Bad Category", "body": "Test", "category": "sports"},
        headers={"Authorization": "Bearer proof_test123"},
    )
    assert resp.status_code == 422


@patch("agentblog.app.main.httpx.AsyncClient")
def test_create_post_too_many_tags(mock_async_client, client):
    mock_async_client.return_value = _mock_registry_success()

    resp = client.post(
        "/v1/posts",
        json={
            "title": "Too Many Tags",
            "body": "Test",
            "category": "technology",
            "tags": ["a", "b", "c", "d", "e", "f"],
        },
        headers={"Authorization": "Bearer proof_test123"},
    )
    assert resp.status_code == 422


# --- List posts ---


@patch("agentblog.app.main.httpx.AsyncClient")
def test_list_posts(mock_async_client, client):
    mock_async_client.return_value = _mock_registry_success("bot_a")
    client.post(
        "/v1/posts",
        json={"title": "First", "body": "First post", "category": "technology"},
        headers={"Authorization": "Bearer proof_test123"},
    )

    mock_async_client.return_value = _mock_registry_success("bot_b")
    client.post(
        "/v1/posts",
        json={"title": "Second", "body": "Second post", "category": "business"},
        headers={"Authorization": "Bearer proof_test123"},
    )

    resp = client.get("/v1/posts")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 2
    # Newest first
    assert data["posts"][0]["title"] == "Second"
    assert data["posts"][1]["title"] == "First"


@patch("agentblog.app.main.httpx.AsyncClient")
def test_list_posts_filter_by_category(mock_async_client, client):
    mock_async_client.return_value = _mock_registry_success("bot_a")
    client.post(
        "/v1/posts",
        json={"title": "Tech Post", "body": "About tech", "category": "technology"},
        headers={"Authorization": "Bearer proof_test123"},
    )

    mock_async_client.return_value = _mock_registry_success("bot_b")
    client.post(
        "/v1/posts",
        json={"title": "Biz Post", "body": "About business", "category": "business"},
        headers={"Authorization": "Bearer proof_test123"},
    )

    resp = client.get("/v1/posts?category=technology")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1
    assert data["posts"][0]["title"] == "Tech Post"


def test_list_posts_empty(client):
    resp = client.get("/v1/posts")
    assert resp.status_code == 200
    assert resp.json()["count"] == 0


# --- List posts by agent ---


@patch("agentblog.app.main.httpx.AsyncClient")
def test_list_agent_posts(mock_async_client, client):
    # Post from two different agents
    mock_async_client.return_value = _mock_registry_success("alpha_bot")
    client.post(
        "/v1/posts",
        json={"title": "Alpha Post", "body": "From alpha", "category": "technology"},
        headers={"Authorization": "Bearer proof_alpha"},
    )

    mock_async_client.return_value = _mock_registry_success("beta_bot")
    client.post(
        "/v1/posts",
        json={"title": "Beta Post", "body": "From beta", "category": "business"},
        headers={"Authorization": "Bearer proof_beta"},
    )

    resp = client.get("/v1/posts/by/alpha_bot")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1
    assert data["posts"][0]["agent_name"] == "alpha_bot"


def test_list_agent_posts_empty(client):
    resp = client.get("/v1/posts/by/nobody")
    assert resp.status_code == 200
    assert resp.json()["count"] == 0


# --- Get single post ---


@patch("agentblog.app.main.httpx.AsyncClient")
def test_get_post(mock_async_client, client):
    mock_async_client.return_value = _mock_registry_success()

    client.post(
        "/v1/posts",
        json={"title": "Single Post", "body": "Get me by ID", "category": "astrology", "tags": ["stars"]},
        headers={"Authorization": "Bearer proof_test123"},
    )

    resp = client.get("/v1/posts/1")
    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == "Single Post"
    assert data["category"] == "astrology"
    assert data["tags"] == ["stars"]


def test_get_post_not_found(client):
    resp = client.get("/v1/posts/999")
    assert resp.status_code == 404


# --- Categories ---


def test_list_categories(client):
    resp = client.get("/v1/categories")
    assert resp.status_code == 200
    data = resp.json()
    assert data["categories"] == ["technology", "astrology", "business"]


# --- Individual post page ---


@patch("agentblog.app.main.httpx.AsyncClient")
def test_post_page(mock_async_client, client):
    mock_async_client.return_value = _mock_registry_success()

    client.post(
        "/v1/posts",
        json={
            "title": "Full Post",
            "body": "x" * 500,
            "category": "technology",
            "tags": ["ai"],
        },
        headers={"Authorization": "Bearer proof_test123"},
    )

    resp = client.get("/post/1")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "Full Post" in resp.text
    assert "test_bot" in resp.text
    # Full body, not truncated
    assert "x" * 500 in resp.text
    assert "Back to home" in resp.text


def test_post_page_not_found(client):
    resp = client.get("/post/999")
    assert resp.status_code == 404
    assert "text/html" in resp.headers["content-type"]
    assert "Post not found" in resp.text


# --- Rate limiting ---


@patch("agentblog.app.main.httpx.AsyncClient")
def test_post_rate_limit_unverified(mock_async_client, client):
    """Unverified agent: second post should be rate-limited."""
    mock_async_client.return_value = _mock_registry_success()

    resp1 = client.post(
        "/v1/posts",
        json={"title": "First", "body": "OK", "category": "technology"},
        headers={"Authorization": "Bearer proof_test123"},
    )
    assert resp1.status_code == 201

    resp2 = client.post(
        "/v1/posts",
        json={"title": "Second", "body": "Too soon", "category": "technology"},
        headers={"Authorization": "Bearer proof_test123"},
    )
    assert resp2.status_code == 429
    data = resp2.json()
    assert "Rate limit" in data["detail"]
    assert data["retry_after"] > 0
    assert "Retry-After" in resp2.headers


@patch("agentblog.app.main.httpx.AsyncClient")
def test_post_rate_limit_different_agents(mock_async_client, client):
    """Different agents should have independent rate limits."""
    mock_async_client.return_value = _mock_registry_success("agent_a")
    resp1 = client.post(
        "/v1/posts",
        json={"title": "From A", "body": "OK", "category": "technology"},
        headers={"Authorization": "Bearer proof_a"},
    )
    assert resp1.status_code == 201

    mock_async_client.return_value = _mock_registry_success("agent_b")
    resp2 = client.post(
        "/v1/posts",
        json={"title": "From B", "body": "Also OK", "category": "technology"},
        headers={"Authorization": "Bearer proof_b"},
    )
    assert resp2.status_code == 201
