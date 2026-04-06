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
    """Replace the module-level store with a fresh in-memory DB and reset rate limiters for each test."""
    fresh = BoardStore(db_path=":memory:")
    main.store = fresh
    main.agent_post_limiter._last_post.clear()
    main.agent_reply_limiter._last_post.clear()
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


def _create_post(client, message="Hello!", tags=None, agent_name="test_bot"):
    """Helper: create a post and reset the rate limiter for the next call."""
    with patch("agentboard.app.main.httpx.AsyncClient") as mock:
        mock.return_value = _mock_registry_success(agent_name)
        body = {"message": message}
        if tags is not None:
            body["tags"] = tags
        resp = client.post(
            "/v1/posts",
            json=body,
            headers={"Authorization": "Bearer proof_test"},
        )
        main.agent_post_limiter.reset(agent_name)
        return resp


# --- Landing page (HTML) ---


def test_landing_page_root(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "AgentBoard" in resp.text
    assert "skill.md" in resp.text


def test_landing_page_links_use_new_domain(client):
    """Landing page HTML must link to agentloka.ai, not iagents.cc."""
    resp = client.get("/")
    assert "agentloka.ai" in resp.text
    assert "iagents.cc" not in resp.text


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
    assert "rules.md" in resp.text
    assert "skill.json" in resp.text


# --- Heartbeat page ---


def test_heartbeat_page(client):
    resp = client.get("/heartbeat.md")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "text/markdown; charset=utf-8"
    assert "Heartbeat" in resp.text
    assert "Step 1" in resp.text


# --- Rules page ---


def test_rules_page(client):
    resp = client.get("/rules.md")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "text/markdown; charset=utf-8"
    assert "Community Rules" in resp.text
    assert "Be Genuine" in resp.text
    assert "Rate Limits" in resp.text


# --- Skill JSON ---


def test_skill_json(client):
    resp = client.get("/skill.json")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/json"
    data = resp.json()
    assert data["name"] == "agentboard"
    assert data["agentauth"]["category"] == "social"
    assert "skill.md" in data["agentauth"]["files"]
    assert "rules.md" in data["agentauth"]["files"]
    assert "heartbeat.md" in data["agentauth"]["files"]
    assert data["agentauth"]["limits"]["message_max_length"] == 280
    # Domain must point to agentloka.ai
    assert "agentloka.ai" in data["homepage"]
    assert "iagents.cc" not in data["homepage"]


def test_skill_json_triggers_use_new_domain(client):
    """skill.json triggers must reference the new domain."""
    data = client.get("/skill.json").json()
    triggers = data["agentauth"]["triggers"]
    assert any("agentloka.ai" in t for t in triggers)
    assert not any("iagents.cc" in t for t in triggers)


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
    assert data["tags"] == []
    assert data["reply_count"] == 0


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
    # Error message should point to the new domain for getting a proof token
    detail = resp.json()["detail"]
    assert "agentloka.ai" in detail
    assert "iagents.cc" not in detail


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


# --- Tags ---


def test_create_post_with_tags(client):
    resp = _create_post(client, message="Tagged post", tags=["ai", "agents"])
    assert resp.status_code == 201
    data = resp.json()
    assert data["tags"] == ["ai", "agents"]


def test_create_post_too_many_tags(client):
    resp = _create_post(client, message="Too many tags", tags=["a", "b", "c", "d", "e", "f"])
    assert resp.status_code == 422


@patch("agentboard.app.main.httpx.AsyncClient")
def test_list_posts_filter_by_tag(mock_async_client, client):
    _create_post(client, message="AI post", tags=["ai"])
    _create_post(client, message="Music post", tags=["music"])
    _create_post(client, message="Both post", tags=["ai", "music"])

    mock_async_client.return_value = _mock_registry_success()
    resp = client.get("/v1/posts?tag=ai", headers={"Authorization": "Bearer proof_read"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_count"] == 2
    messages = [p["message"] for p in data["posts"]]
    assert "AI post" in messages
    assert "Both post" in messages
    assert "Music post" not in messages


@patch("agentboard.app.main.httpx.AsyncClient")
def test_list_tags(mock_async_client, client):
    _create_post(client, message="Post 1", tags=["ai", "agents"])
    _create_post(client, message="Post 2", tags=["music", "ai"])

    mock_async_client.return_value = _mock_registry_success()
    resp = client.get("/v1/tags", headers={"Authorization": "Bearer proof_read"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["tags"] == ["agents", "ai", "music"]
    assert data["count"] == 3


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

    mock_async_client.return_value = _mock_registry_success()
    resp = client.get("/v1/posts", headers={"Authorization": "Bearer proof_read"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 2
    assert data["total_count"] == 2
    assert data["page"] == 1
    # Newest first
    assert data["posts"][0]["message"] == "Second post"
    assert data["posts"][1]["message"] == "First post"


@patch("agentboard.app.main.httpx.AsyncClient")
def test_list_posts_empty(mock_async_client, client):
    mock_async_client.return_value = _mock_registry_success()
    resp = client.get("/v1/posts", headers={"Authorization": "Bearer proof_read"})
    assert resp.status_code == 200
    assert resp.json()["count"] == 0


# --- Pagination ---


@patch("agentboard.app.main.httpx.AsyncClient")
def test_list_posts_pagination(mock_async_client, client):
    """Create 3 posts, request page=1 limit=2 — should get 2 posts, total_count=3."""
    for i in range(3):
        _create_post(client, message=f"Post {i}", agent_name=f"bot_{i}")

    mock_async_client.return_value = _mock_registry_success()
    resp = client.get("/v1/posts?page=1&limit=2", headers={"Authorization": "Bearer proof_read"})
    data = resp.json()
    assert data["count"] == 2
    assert data["total_count"] == 3
    assert data["page"] == 1
    assert data["limit"] == 2


@patch("agentboard.app.main.httpx.AsyncClient")
def test_list_posts_page_2(mock_async_client, client):
    """Page 2 with limit=2 from 3 posts should return 1 post."""
    for i in range(3):
        _create_post(client, message=f"Post {i}", agent_name=f"bot_{i}")

    mock_async_client.return_value = _mock_registry_success()
    resp = client.get("/v1/posts?page=2&limit=2", headers={"Authorization": "Bearer proof_read"})
    data = resp.json()
    assert data["count"] == 1
    assert data["total_count"] == 3
    assert data["page"] == 2


@patch("agentboard.app.main.httpx.AsyncClient")
def test_list_agent_posts_pagination(mock_async_client, client):
    """Pagination on the agent-specific endpoint."""
    for i in range(3):
        _create_post(client, message=f"Post {i}", agent_name="same_bot")

    mock_async_client.return_value = _mock_registry_success()
    resp = client.get("/v1/posts/same_bot?page=1&limit=2", headers={"Authorization": "Bearer proof_read"})
    data = resp.json()
    assert data["count"] == 2
    assert data["total_count"] == 3


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

    mock_async_client.return_value = _mock_registry_success()
    resp = client.get("/v1/posts/alpha_bot", headers={"Authorization": "Bearer proof_read"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1
    assert data["total_count"] == 1
    assert data["posts"][0]["agent_name"] == "alpha_bot"


@patch("agentboard.app.main.httpx.AsyncClient")
def test_list_agent_posts_empty(mock_async_client, client):
    mock_async_client.return_value = _mock_registry_success()
    resp = client.get("/v1/posts/nobody", headers={"Authorization": "Bearer proof_read"})
    assert resp.status_code == 200
    assert resp.json()["count"] == 0


# --- Delete own post ---


@patch("agentboard.app.main.httpx.AsyncClient")
def test_delete_own_post(mock_async_client, client):
    """Agent can delete their own post — 204, then post is gone."""
    _create_post(client, message="Delete me", agent_name="test_bot")

    mock_async_client.return_value = _mock_registry_success("test_bot")
    resp = client.delete("/v1/posts/1", headers={"Authorization": "Bearer proof_del"})
    assert resp.status_code == 204

    # Verify gone
    mock_async_client.return_value = _mock_registry_success()
    resp = client.get("/v1/posts", headers={"Authorization": "Bearer proof_read"})
    assert resp.json()["count"] == 0


@patch("agentboard.app.main.httpx.AsyncClient")
def test_delete_other_agents_post_forbidden(mock_async_client, client):
    """Deleting another agent's post returns 403."""
    _create_post(client, message="Not yours", agent_name="agent_a")

    mock_async_client.return_value = _mock_registry_success("agent_b")
    resp = client.delete("/v1/posts/1", headers={"Authorization": "Bearer proof_del"})
    assert resp.status_code == 403


@patch("agentboard.app.main.httpx.AsyncClient")
def test_delete_post_not_found(mock_async_client, client):
    """Deleting a non-existent post returns 404."""
    mock_async_client.return_value = _mock_registry_success()
    resp = client.delete("/v1/posts/999", headers={"Authorization": "Bearer proof_del"})
    assert resp.status_code == 404


# --- Replies ---


@patch("agentboard.app.main.httpx.AsyncClient")
def test_create_reply(mock_async_client, client):
    """Create a reply on an existing post — 201 with reply fields."""
    _create_post(client, message="Original post")

    mock_async_client.return_value = _mock_registry_success("replier")
    resp = client.post(
        "/v1/posts/1/replies",
        json={"body": "Great post!"},
        headers={"Authorization": "Bearer proof_reply"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["post_id"] == 1
    assert data["agent_name"] == "replier"
    assert data["body"] == "Great post!"


@patch("agentboard.app.main.httpx.AsyncClient")
def test_create_reply_nonexistent_post(mock_async_client, client):
    """Reply to a non-existent post returns 404."""
    mock_async_client.return_value = _mock_registry_success()
    resp = client.post(
        "/v1/posts/999/replies",
        json={"body": "Reply to nothing"},
        headers={"Authorization": "Bearer proof_reply"},
    )
    assert resp.status_code == 404


@patch("agentboard.app.main.httpx.AsyncClient")
def test_list_replies(mock_async_client, client):
    """List replies on a post — oldest first, with pagination fields."""
    _create_post(client, message="Original post")

    # Create two replies from different agents
    mock_async_client.return_value = _mock_registry_success("bot_a")
    client.post(
        "/v1/posts/1/replies",
        json={"body": "First reply"},
        headers={"Authorization": "Bearer proof_a"},
    )
    main.agent_reply_limiter.reset("bot_a")

    mock_async_client.return_value = _mock_registry_success("bot_b")
    client.post(
        "/v1/posts/1/replies",
        json={"body": "Second reply"},
        headers={"Authorization": "Bearer proof_b"},
    )

    mock_async_client.return_value = _mock_registry_success()
    resp = client.get("/v1/posts/1/replies", headers={"Authorization": "Bearer proof_read"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 2
    assert data["total_count"] == 2
    # Oldest first
    assert data["replies"][0]["body"] == "First reply"
    assert data["replies"][1]["body"] == "Second reply"


@patch("agentboard.app.main.httpx.AsyncClient")
def test_delete_own_reply(mock_async_client, client):
    """Agent can delete their own reply — 204."""
    _create_post(client, message="A post")

    mock_async_client.return_value = _mock_registry_success("replier")
    client.post(
        "/v1/posts/1/replies",
        json={"body": "My reply"},
        headers={"Authorization": "Bearer proof_reply"},
    )

    mock_async_client.return_value = _mock_registry_success("replier")
    resp = client.delete("/v1/posts/1/replies/1", headers={"Authorization": "Bearer proof_del"})
    assert resp.status_code == 204

    # Verify gone
    mock_async_client.return_value = _mock_registry_success()
    resp = client.get("/v1/posts/1/replies", headers={"Authorization": "Bearer proof_read"})
    assert resp.json()["count"] == 0


@patch("agentboard.app.main.httpx.AsyncClient")
def test_delete_other_agents_reply_forbidden(mock_async_client, client):
    """Deleting another agent's reply returns 403."""
    _create_post(client, message="A post")

    mock_async_client.return_value = _mock_registry_success("agent_a")
    client.post(
        "/v1/posts/1/replies",
        json={"body": "Agent A's reply"},
        headers={"Authorization": "Bearer proof_a"},
    )

    mock_async_client.return_value = _mock_registry_success("agent_b")
    resp = client.delete("/v1/posts/1/replies/1", headers={"Authorization": "Bearer proof_del"})
    assert resp.status_code == 403


@patch("agentboard.app.main.httpx.AsyncClient")
def test_reply_rate_limit(mock_async_client, client):
    """Second reply in quick succession should be rate-limited (429)."""
    _create_post(client, message="A post")

    mock_async_client.return_value = _mock_registry_success("fast_replier")
    resp1 = client.post(
        "/v1/posts/1/replies",
        json={"body": "First reply"},
        headers={"Authorization": "Bearer proof_reply"},
    )
    assert resp1.status_code == 201

    resp2 = client.post(
        "/v1/posts/1/replies",
        json={"body": "Too soon"},
        headers={"Authorization": "Bearer proof_reply"},
    )
    assert resp2.status_code == 429
    assert resp2.json()["retry_after"] > 0


@patch("agentboard.app.main.httpx.AsyncClient")
def test_reply_count_in_post(mock_async_client, client):
    """Post response should include reply_count."""
    _create_post(client, message="A post")

    mock_async_client.return_value = _mock_registry_success("replier")
    client.post(
        "/v1/posts/1/replies",
        json={"body": "A reply"},
        headers={"Authorization": "Bearer proof_reply"},
    )

    mock_async_client.return_value = _mock_registry_success()
    resp = client.get("/v1/posts", headers={"Authorization": "Bearer proof_read"})
    assert resp.json()["posts"][0]["reply_count"] == 1


# --- HTML pages ---


def test_agent_profile_page(client):
    """Agent profile page shows the agent's posts."""
    _create_post(client, message="My post", agent_name="profile_bot")

    resp = client.get("/agent/profile_bot")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "profile_bot" in resp.text
    assert "My post" in resp.text


def test_agent_profile_page_empty(client):
    resp = client.get("/agent/nobody")
    assert resp.status_code == 200
    assert "No posts yet" in resp.text


def test_tag_page(client):
    """Tag page shows posts with that tag."""
    _create_post(client, message="AI thoughts", tags=["ai"])

    resp = client.get("/tag/ai")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "#ai" in resp.text
    assert "AI thoughts" in resp.text


def test_tag_page_empty(client):
    resp = client.get("/tag/nonexistent")
    assert resp.status_code == 200
    assert "No posts yet" in resp.text


def test_landing_page_shows_tags(client):
    """Landing page should display tags on posts."""
    _create_post(client, message="Tagged", tags=["hello"])

    resp = client.get("/")
    assert "#hello" in resp.text


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
