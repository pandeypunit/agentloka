"""Tests for AgentBoard — message board powered by AgentAuth."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from agentboard.app import main
from agentboard.app.main import app
from agentboard.app.store import BoardStore

# Patch target for SDK-based verify in verify_agent()
_VERIFY_PATCH = "agentboard.app.main._auth.verify_proof_token_via_registry_async"


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


def _mock_verify_success(agent_name="test_bot", description="A test agent"):
    """Return value for a successful SDK verify call."""
    return {
        "name": agent_name,
        "description": description,
        "verified": False,
        "active": True,
    }


def _create_post(client, message="Hello!", tags=None, agent_name="test_bot"):
    """Helper: create a post and reset the rate limiter for the next call."""
    with patch(_VERIFY_PATCH, new_callable=AsyncMock) as mock_verify:
        mock_verify.return_value = _mock_verify_success(agent_name)
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


@patch(_VERIFY_PATCH, new_callable=AsyncMock)
def test_landing_page_with_posts(mock_verify, client):
    mock_verify.return_value = _mock_verify_success()

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


@patch(_VERIFY_PATCH, new_callable=AsyncMock)
def test_create_post(mock_verify, client):
    mock_verify.return_value = _mock_verify_success()

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


@patch(_VERIFY_PATCH, new_callable=AsyncMock)
def test_create_post_increments_id(mock_verify, client):
    mock_verify.return_value = _mock_verify_success("bot_a")
    client.post(
        "/v1/posts",
        json={"message": "First"},
        headers={"Authorization": "Bearer proof_test123"},
    )

    mock_verify.return_value = _mock_verify_success("bot_b")
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


@patch(_VERIFY_PATCH, new_callable=AsyncMock)
def test_create_post_invalid_key(mock_verify, client):
    mock_verify.return_value = None

    resp = client.post(
        "/v1/posts",
        json={"message": "Bad key"},
        headers={"Authorization": "Bearer proof_fake"},
    )
    assert resp.status_code == 401
    assert "not verified" in resp.json()["detail"]


@patch(_VERIFY_PATCH, new_callable=AsyncMock)
def test_create_post_too_long(mock_verify, client):
    mock_verify.return_value = _mock_verify_success()

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


@patch(_VERIFY_PATCH, new_callable=AsyncMock)
def test_list_posts_filter_by_tag(mock_verify, client):
    _create_post(client, message="AI post", tags=["ai"])
    _create_post(client, message="Music post", tags=["music"])
    _create_post(client, message="Both post", tags=["ai", "music"])

    mock_verify.return_value = _mock_verify_success()
    resp = client.get("/v1/posts?tag=ai", headers={"Authorization": "Bearer proof_read"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_count"] == 2
    messages = [p["message"] for p in data["posts"]]
    assert "AI post" in messages
    assert "Both post" in messages
    assert "Music post" not in messages


@patch(_VERIFY_PATCH, new_callable=AsyncMock)
def test_list_tags(mock_verify, client):
    _create_post(client, message="Post 1", tags=["ai", "agents"])
    _create_post(client, message="Post 2", tags=["music", "ai"])

    mock_verify.return_value = _mock_verify_success()
    resp = client.get("/v1/tags", headers={"Authorization": "Bearer proof_read"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["tags"] == ["agents", "ai", "music"]
    assert data["count"] == 3


# --- List posts ---


@patch(_VERIFY_PATCH, new_callable=AsyncMock)
def test_list_posts(mock_verify, client):
    mock_verify.return_value = _mock_verify_success("bot_a")
    client.post(
        "/v1/posts",
        json={"message": "First post"},
        headers={"Authorization": "Bearer proof_test123"},
    )

    mock_verify.return_value = _mock_verify_success("bot_b")
    client.post(
        "/v1/posts",
        json={"message": "Second post"},
        headers={"Authorization": "Bearer proof_test123"},
    )

    mock_verify.return_value = _mock_verify_success()
    resp = client.get("/v1/posts", headers={"Authorization": "Bearer proof_read"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 2
    assert data["total_count"] == 2
    assert data["page"] == 1
    # Newest first
    assert data["posts"][0]["message"] == "Second post"
    assert data["posts"][1]["message"] == "First post"


@patch(_VERIFY_PATCH, new_callable=AsyncMock)
def test_list_posts_empty(mock_verify, client):
    mock_verify.return_value = _mock_verify_success()
    resp = client.get("/v1/posts", headers={"Authorization": "Bearer proof_read"})
    assert resp.status_code == 200
    assert resp.json()["count"] == 0


# --- Pagination ---


@patch(_VERIFY_PATCH, new_callable=AsyncMock)
def test_list_posts_pagination(mock_verify, client):
    """Create 3 posts, request page=1 limit=2 — should get 2 posts, total_count=3."""
    for i in range(3):
        _create_post(client, message=f"Post {i}", agent_name=f"bot_{i}")

    mock_verify.return_value = _mock_verify_success()
    resp = client.get("/v1/posts?page=1&limit=2", headers={"Authorization": "Bearer proof_read"})
    data = resp.json()
    assert data["count"] == 2
    assert data["total_count"] == 3
    assert data["page"] == 1
    assert data["limit"] == 2


@patch(_VERIFY_PATCH, new_callable=AsyncMock)
def test_list_posts_page_2(mock_verify, client):
    """Page 2 with limit=2 from 3 posts should return 1 post."""
    for i in range(3):
        _create_post(client, message=f"Post {i}", agent_name=f"bot_{i}")

    mock_verify.return_value = _mock_verify_success()
    resp = client.get("/v1/posts?page=2&limit=2", headers={"Authorization": "Bearer proof_read"})
    data = resp.json()
    assert data["count"] == 1
    assert data["total_count"] == 3
    assert data["page"] == 2


@patch(_VERIFY_PATCH, new_callable=AsyncMock)
def test_list_agent_posts_pagination(mock_verify, client):
    """Pagination on the agent-specific endpoint."""
    for i in range(3):
        _create_post(client, message=f"Post {i}", agent_name="same_bot")

    mock_verify.return_value = _mock_verify_success()
    resp = client.get("/v1/posts/same_bot?page=1&limit=2", headers={"Authorization": "Bearer proof_read"})
    data = resp.json()
    assert data["count"] == 2
    assert data["total_count"] == 3


# --- List posts by agent ---


@patch(_VERIFY_PATCH, new_callable=AsyncMock)
def test_list_agent_posts(mock_verify, client):
    # Post from two different agents
    mock_verify.return_value = _mock_verify_success("alpha_bot")
    client.post(
        "/v1/posts",
        json={"message": "Alpha says hi"},
        headers={"Authorization": "Bearer proof_alpha"},
    )

    mock_verify.return_value = _mock_verify_success("beta_bot")
    client.post(
        "/v1/posts",
        json={"message": "Beta says hi"},
        headers={"Authorization": "Bearer proof_beta"},
    )

    mock_verify.return_value = _mock_verify_success()
    resp = client.get("/v1/posts/alpha_bot", headers={"Authorization": "Bearer proof_read"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1
    assert data["total_count"] == 1
    assert data["posts"][0]["agent_name"] == "alpha_bot"


@patch(_VERIFY_PATCH, new_callable=AsyncMock)
def test_list_agent_posts_empty(mock_verify, client):
    mock_verify.return_value = _mock_verify_success()
    resp = client.get("/v1/posts/nobody", headers={"Authorization": "Bearer proof_read"})
    assert resp.status_code == 200
    assert resp.json()["count"] == 0


# --- Delete own post ---


@patch(_VERIFY_PATCH, new_callable=AsyncMock)
def test_delete_own_post(mock_verify, client):
    """Agent can delete their own post — 204, then post is gone."""
    _create_post(client, message="Delete me", agent_name="test_bot")

    mock_verify.return_value = _mock_verify_success("test_bot")
    resp = client.delete("/v1/posts/1", headers={"Authorization": "Bearer proof_del"})
    assert resp.status_code == 204

    # Verify gone
    mock_verify.return_value = _mock_verify_success()
    resp = client.get("/v1/posts", headers={"Authorization": "Bearer proof_read"})
    assert resp.json()["count"] == 0


@patch(_VERIFY_PATCH, new_callable=AsyncMock)
def test_delete_other_agents_post_forbidden(mock_verify, client):
    """Deleting another agent's post returns 403."""
    _create_post(client, message="Not yours", agent_name="agent_a")

    mock_verify.return_value = _mock_verify_success("agent_b")
    resp = client.delete("/v1/posts/1", headers={"Authorization": "Bearer proof_del"})
    assert resp.status_code == 403


@patch(_VERIFY_PATCH, new_callable=AsyncMock)
def test_delete_post_not_found(mock_verify, client):
    """Deleting a non-existent post returns 404."""
    mock_verify.return_value = _mock_verify_success()
    resp = client.delete("/v1/posts/999", headers={"Authorization": "Bearer proof_del"})
    assert resp.status_code == 404


# --- Replies ---


@patch(_VERIFY_PATCH, new_callable=AsyncMock)
def test_create_reply(mock_verify, client):
    """Create a reply on an existing post — 201 with reply fields."""
    _create_post(client, message="Original post")

    mock_verify.return_value = _mock_verify_success("replier")
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


@patch(_VERIFY_PATCH, new_callable=AsyncMock)
def test_create_reply_nonexistent_post(mock_verify, client):
    """Reply to a non-existent post returns 404."""
    mock_verify.return_value = _mock_verify_success()
    resp = client.post(
        "/v1/posts/999/replies",
        json={"body": "Reply to nothing"},
        headers={"Authorization": "Bearer proof_reply"},
    )
    assert resp.status_code == 404


@patch(_VERIFY_PATCH, new_callable=AsyncMock)
def test_list_replies(mock_verify, client):
    """List replies on a post — oldest first, with pagination fields."""
    _create_post(client, message="Original post")

    # Create two replies from different agents
    mock_verify.return_value = _mock_verify_success("bot_a")
    client.post(
        "/v1/posts/1/replies",
        json={"body": "First reply"},
        headers={"Authorization": "Bearer proof_a"},
    )
    main.agent_reply_limiter.reset("bot_a")

    mock_verify.return_value = _mock_verify_success("bot_b")
    client.post(
        "/v1/posts/1/replies",
        json={"body": "Second reply"},
        headers={"Authorization": "Bearer proof_b"},
    )

    mock_verify.return_value = _mock_verify_success()
    resp = client.get("/v1/posts/1/replies", headers={"Authorization": "Bearer proof_read"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 2
    assert data["total_count"] == 2
    # Oldest first
    assert data["replies"][0]["body"] == "First reply"
    assert data["replies"][1]["body"] == "Second reply"


@patch(_VERIFY_PATCH, new_callable=AsyncMock)
def test_delete_own_reply(mock_verify, client):
    """Agent can delete their own reply — 204."""
    _create_post(client, message="A post")

    mock_verify.return_value = _mock_verify_success("replier")
    client.post(
        "/v1/posts/1/replies",
        json={"body": "My reply"},
        headers={"Authorization": "Bearer proof_reply"},
    )

    mock_verify.return_value = _mock_verify_success("replier")
    resp = client.delete("/v1/posts/1/replies/1", headers={"Authorization": "Bearer proof_del"})
    assert resp.status_code == 204

    # Verify gone
    mock_verify.return_value = _mock_verify_success()
    resp = client.get("/v1/posts/1/replies", headers={"Authorization": "Bearer proof_read"})
    assert resp.json()["count"] == 0


@patch(_VERIFY_PATCH, new_callable=AsyncMock)
def test_delete_other_agents_reply_forbidden(mock_verify, client):
    """Deleting another agent's reply returns 403."""
    _create_post(client, message="A post")

    mock_verify.return_value = _mock_verify_success("agent_a")
    client.post(
        "/v1/posts/1/replies",
        json={"body": "Agent A's reply"},
        headers={"Authorization": "Bearer proof_a"},
    )

    mock_verify.return_value = _mock_verify_success("agent_b")
    resp = client.delete("/v1/posts/1/replies/1", headers={"Authorization": "Bearer proof_del"})
    assert resp.status_code == 403


@patch(_VERIFY_PATCH, new_callable=AsyncMock)
def test_reply_rate_limit(mock_verify, client):
    """Second reply in quick succession should be rate-limited (429)."""
    _create_post(client, message="A post")

    mock_verify.return_value = _mock_verify_success("fast_replier")
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


@patch(_VERIFY_PATCH, new_callable=AsyncMock)
def test_reply_count_in_post(mock_verify, client):
    """Post response should include reply_count."""
    _create_post(client, message="A post")

    mock_verify.return_value = _mock_verify_success("replier")
    client.post(
        "/v1/posts/1/replies",
        json={"body": "A reply"},
        headers={"Authorization": "Bearer proof_reply"},
    )

    mock_verify.return_value = _mock_verify_success()
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


@patch(_VERIFY_PATCH, new_callable=AsyncMock)
def test_post_rate_limit_unverified(mock_verify, client):
    """Unverified agent: second post should be rate-limited."""
    mock_verify.return_value = _mock_verify_success()

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


@patch(_VERIFY_PATCH, new_callable=AsyncMock)
def test_post_rate_limit_different_agents(mock_verify, client):
    """Different agents should have independent rate limits."""
    mock_verify.return_value = _mock_verify_success("agent_a")
    resp1 = client.post(
        "/v1/posts",
        json={"message": "From A"},
        headers={"Authorization": "Bearer proof_a"},
    )
    assert resp1.status_code == 201

    mock_verify.return_value = _mock_verify_success("agent_b")
    resp2 = client.post(
        "/v1/posts",
        json={"message": "From B"},
        headers={"Authorization": "Bearer proof_b"},
    )
    assert resp2.status_code == 201


# --- Hashtag extraction ---


def test_hashtag_extraction(client):
    """Hashtags in message text are auto-extracted into tags."""
    resp = _create_post(client, message="Hello #ai #agents world")
    assert resp.status_code == 201
    data = resp.json()
    assert "ai" in data["tags"]
    assert "agents" in data["tags"]


def test_hashtag_merge_with_explicit_tags(client):
    """Explicit tags and hashtags from message are merged."""
    resp = _create_post(client, message="Check #ai news", tags=["intro"])
    assert resp.status_code == 201
    data = resp.json()
    assert "intro" in data["tags"]
    assert "ai" in data["tags"]


def test_hashtag_dedup(client):
    """Duplicate between explicit tags and hashtags is deduplicated."""
    resp = _create_post(client, message="Love #ai", tags=["ai"])
    assert resp.status_code == 201
    data = resp.json()
    assert data["tags"].count("ai") == 1


def test_hashtag_cap_at_five(client):
    """Total tags (explicit + extracted) capped at 5."""
    resp = _create_post(client, message="#a #b #c #d #e #f #g")
    assert resp.status_code == 201
    data = resp.json()
    assert len(data["tags"]) == 5


def test_hashtag_invalid_ignored(client):
    """Numeric-only hashtags like #123 are not extracted."""
    resp = _create_post(client, message="Test #123 and # alone")
    assert resp.status_code == 201
    data = resp.json()
    assert data["tags"] == []


def test_hashtag_rendered_as_links(client):
    """HTML output renders hashtags in message as clickable links."""
    _create_post(client, message="Hello #ai world")

    resp = client.get("/")
    assert resp.status_code == 200
    assert 'href="/tag/ai">#ai</a>' in resp.text


def test_url_rendered_as_link(client):
    """URLs in message are rendered as clickable links opening in new tab."""
    _create_post(client, message="Check https://agentloka.ai/ for info")

    resp = client.get("/")
    assert resp.status_code == 200
    assert 'href="https://agentloka.ai/"' in resp.text
    assert 'target="_blank"' in resp.text
    assert 'rel="noopener noreferrer"' in resp.text


def test_url_and_hashtag_together(client):
    """Message with both URL and hashtag renders both correctly."""
    _create_post(client, message="See https://example.com #ai")

    resp = client.get("/")
    assert 'href="https://example.com"' in resp.text
    assert 'href="/tag/ai">#ai</a>' in resp.text
