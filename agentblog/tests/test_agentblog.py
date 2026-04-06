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
    main.agent_comment_limiter._last_post.clear()
    yield
    fresh.close()


@pytest.fixture
def client():
    return TestClient(app)


def _mock_registry_success(agent_name="test_bot", description="A test agent", verified=False):
    """Create a mock that simulates a successful proof token verification."""
    mock_response = AsyncMock()
    mock_response.status_code = 200
    # httpx .json() is sync, not async
    mock_response.json = lambda: {
        "name": agent_name,
        "description": description,
        "verified": verified,
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


def _create_post(mock_async_client, client, title="Test Post", body="Test body", category="technology",
                 tags=None, agent_name="test_bot"):
    """Helper to create a post and reset rate limiter."""
    mock_async_client.return_value = _mock_registry_success(agent_name)
    resp = client.post(
        "/v1/posts",
        json={"title": title, "body": body, "category": category, "tags": tags or []},
        headers={"Authorization": "Bearer proof_test123"},
    )
    # Reset rate limiter so multiple posts can be created in tests
    main.agent_post_limiter.reset(agent_name)
    return resp


# --- Landing page (HTML) ---


def test_landing_page_root(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "AgentBlog" in resp.text
    assert "skill.md" in resp.text


def test_landing_page_links_use_new_domain(client):
    """Landing page HTML must link to agentloka.ai, not iagents.cc."""
    resp = client.get("/")
    assert "agentloka.ai" in resp.text
    assert "iagents.cc" not in resp.text


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
    assert data["name"] == "agentblog"
    assert data["agentauth"]["category"] == "blog"
    assert "skill.md" in data["agentauth"]["files"]
    assert "rules.md" in data["agentauth"]["files"]
    assert "heartbeat.md" in data["agentauth"]["files"]
    assert data["agentauth"]["limits"]["body_max_length"] == 8000
    # Domain must point to agentloka.ai
    assert "agentloka.ai" in data["homepage"]
    assert "iagents.cc" not in data["homepage"]


def test_skill_json_triggers_use_new_domain(client):
    """skill.json triggers must reference the new domain."""
    data = client.get("/skill.json").json()
    triggers = data["agentauth"]["triggers"]
    assert any("agentloka.ai" in t for t in triggers)
    assert not any("iagents.cc" in t for t in triggers)


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
    # Error message should point to the new domain for getting a proof token
    detail = resp.json()["detail"]
    assert "agentloka.ai" in detail
    assert "iagents.cc" not in detail


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
    _create_post(mock_async_client, client, title="First", body="First post", category="technology", agent_name="bot_a")
    _create_post(mock_async_client, client, title="Second", body="Second post", category="business", agent_name="bot_b")

    mock_async_client.return_value = _mock_registry_success()
    resp = client.get("/v1/posts", headers={"Authorization": "Bearer proof_read"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 2
    assert data["total_count"] == 2
    assert data["page"] == 1
    # Newest first
    assert data["posts"][0]["title"] == "Second"
    assert data["posts"][1]["title"] == "First"


@patch("agentblog.app.main.httpx.AsyncClient")
def test_list_posts_filter_by_category(mock_async_client, client):
    _create_post(mock_async_client, client, title="Tech Post", body="About tech", category="technology", agent_name="bot_a")
    _create_post(mock_async_client, client, title="Biz Post", body="About business", category="business", agent_name="bot_b")

    mock_async_client.return_value = _mock_registry_success()
    resp = client.get("/v1/posts?category=technology", headers={"Authorization": "Bearer proof_read"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1
    assert data["posts"][0]["title"] == "Tech Post"


@patch("agentblog.app.main.httpx.AsyncClient")
def test_list_posts_empty(mock_async_client, client):
    mock_async_client.return_value = _mock_registry_success()
    resp = client.get("/v1/posts", headers={"Authorization": "Bearer proof_read"})
    assert resp.status_code == 200
    assert resp.json()["count"] == 0


# --- List posts by agent ---


@patch("agentblog.app.main.httpx.AsyncClient")
def test_list_agent_posts(mock_async_client, client):
    _create_post(mock_async_client, client, title="Alpha Post", body="From alpha", category="technology", agent_name="alpha_bot")
    _create_post(mock_async_client, client, title="Beta Post", body="From beta", category="business", agent_name="beta_bot")

    mock_async_client.return_value = _mock_registry_success()
    resp = client.get("/v1/posts/by/alpha_bot", headers={"Authorization": "Bearer proof_read"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1
    assert data["posts"][0]["agent_name"] == "alpha_bot"


@patch("agentblog.app.main.httpx.AsyncClient")
def test_list_agent_posts_empty(mock_async_client, client):
    mock_async_client.return_value = _mock_registry_success()
    resp = client.get("/v1/posts/by/nobody", headers={"Authorization": "Bearer proof_read"})
    assert resp.status_code == 200
    assert resp.json()["count"] == 0


# --- Get single post ---


@patch("agentblog.app.main.httpx.AsyncClient")
def test_get_post(mock_async_client, client):
    _create_post(mock_async_client, client, title="Single Post", body="Get me by ID", category="astrology",
                 tags=["stars"])

    mock_async_client.return_value = _mock_registry_success()
    resp = client.get("/v1/posts/1", headers={"Authorization": "Bearer proof_read"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == "Single Post"
    assert data["category"] == "astrology"
    assert data["tags"] == ["stars"]


@patch("agentblog.app.main.httpx.AsyncClient")
def test_get_post_not_found(mock_async_client, client):
    mock_async_client.return_value = _mock_registry_success()
    resp = client.get("/v1/posts/999", headers={"Authorization": "Bearer proof_read"})
    assert resp.status_code == 404


# --- Categories ---


@patch("agentblog.app.main.httpx.AsyncClient")
def test_list_categories(mock_async_client, client):
    mock_async_client.return_value = _mock_registry_success()
    resp = client.get("/v1/categories", headers={"Authorization": "Bearer proof_read"})
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


@patch("agentblog.app.main.httpx.AsyncClient")
def test_post_page_links_use_new_domain(mock_async_client, client):
    """Individual post page HTML must link to agentloka.ai, not iagents.cc."""
    mock_async_client.return_value = _mock_registry_success()
    client.post(
        "/v1/posts",
        json={"title": "Domain Test", "body": "Check links", "category": "technology"},
        headers={"Authorization": "Bearer proof_test123"},
    )
    resp = client.get("/post/1")
    assert resp.status_code == 200
    assert "iagents.cc" not in resp.text


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


# ============================================================
# Phase 1: Tag filtering, pagination, HTML pages
# ============================================================


@patch("agentblog.app.main.httpx.AsyncClient")
def test_list_posts_filter_by_tag(mock_async_client, client):
    """Filter posts by tag."""
    _create_post(mock_async_client, client, title="AI Post", tags=["ai", "ml"], agent_name="bot_a")
    _create_post(mock_async_client, client, title="Web Post", tags=["web", "frontend"], agent_name="bot_b")
    _create_post(mock_async_client, client, title="Also AI", tags=["ai"], agent_name="bot_c")

    mock_async_client.return_value = _mock_registry_success()
    resp = client.get("/v1/posts?tag=ai", headers={"Authorization": "Bearer proof_read"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 2
    titles = {p["title"] for p in data["posts"]}
    assert titles == {"AI Post", "Also AI"}


@patch("agentblog.app.main.httpx.AsyncClient")
def test_list_posts_filter_by_tag_no_results(mock_async_client, client):
    """Nonexistent tag returns empty list."""
    _create_post(mock_async_client, client, title="Post", tags=["ai"])

    mock_async_client.return_value = _mock_registry_success()
    resp = client.get("/v1/posts?tag=nonexistent", headers={"Authorization": "Bearer proof_read"})
    assert resp.status_code == 200
    assert resp.json()["count"] == 0


@patch("agentblog.app.main.httpx.AsyncClient")
def test_list_posts_combined_tag_and_category(mock_async_client, client):
    """Both tag and category filters at once."""
    _create_post(mock_async_client, client, title="Tech AI", category="technology", tags=["ai"], agent_name="bot_a")
    _create_post(mock_async_client, client, title="Biz AI", category="business", tags=["ai"], agent_name="bot_b")
    _create_post(mock_async_client, client, title="Tech Web", category="technology", tags=["web"], agent_name="bot_c")

    mock_async_client.return_value = _mock_registry_success()
    resp = client.get("/v1/posts?category=technology&tag=ai", headers={"Authorization": "Bearer proof_read"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1
    assert data["posts"][0]["title"] == "Tech AI"


@patch("agentblog.app.main.httpx.AsyncClient")
def test_list_tags(mock_async_client, client):
    """Verify aggregated unique tag list."""
    _create_post(mock_async_client, client, title="P1", tags=["ai", "ml"], agent_name="bot_a")
    _create_post(mock_async_client, client, title="P2", tags=["ai", "web"], agent_name="bot_b")

    mock_async_client.return_value = _mock_registry_success()
    resp = client.get("/v1/tags", headers={"Authorization": "Bearer proof_read"})
    assert resp.status_code == 200
    data = resp.json()
    assert set(data["tags"]) == {"ai", "ml", "web"}
    assert data["count"] == 3


@patch("agentblog.app.main.httpx.AsyncClient")
def test_list_tags_empty(mock_async_client, client):
    """No posts, empty tags."""
    mock_async_client.return_value = _mock_registry_success()
    resp = client.get("/v1/tags", headers={"Authorization": "Bearer proof_read"})
    assert resp.status_code == 200
    assert resp.json()["tags"] == []
    assert resp.json()["count"] == 0


@patch("agentblog.app.main.httpx.AsyncClient")
def test_list_posts_pagination(mock_async_client, client):
    """Create >20 posts, verify page 1 and page 2."""
    for i in range(25):
        _create_post(mock_async_client, client, title=f"Post {i}", agent_name=f"bot_{i}")

    mock_async_client.return_value = _mock_registry_success()
    # Page 1
    resp1 = client.get("/v1/posts?page=1&limit=20", headers={"Authorization": "Bearer proof_read"})
    data1 = resp1.json()
    assert data1["count"] == 20
    assert data1["total_count"] == 25
    assert data1["page"] == 1

    # Page 2
    resp2 = client.get("/v1/posts?page=2&limit=20", headers={"Authorization": "Bearer proof_read"})
    data2 = resp2.json()
    assert data2["count"] == 5
    assert data2["total_count"] == 25
    assert data2["page"] == 2


@patch("agentblog.app.main.httpx.AsyncClient")
def test_category_html_page(mock_async_client, client):
    """GET /technology returns HTML with correct posts."""
    _create_post(mock_async_client, client, title="Tech Article", category="technology")
    _create_post(mock_async_client, client, title="Biz Article", category="business", agent_name="bot_b")

    resp = client.get("/technology")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "Tech Article" in resp.text
    assert "Biz Article" not in resp.text


def test_category_html_page_not_found(client):
    """Invalid category returns 404."""
    resp = client.get("/sports")
    assert resp.status_code == 404


@patch("agentblog.app.main.httpx.AsyncClient")
def test_agent_html_page(mock_async_client, client):
    """GET /agent/test_bot returns HTML."""
    _create_post(mock_async_client, client, title="My Post")

    resp = client.get("/agent/test_bot")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "My Post" in resp.text
    assert "test_bot" in resp.text


@patch("agentblog.app.main.httpx.AsyncClient")
def test_tag_html_page(mock_async_client, client):
    """GET /tag/ai returns HTML."""
    _create_post(mock_async_client, client, title="AI Post", tags=["ai", "ml"])

    resp = client.get("/tag/ai")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "AI Post" in resp.text


# ============================================================
# Phase 2: Edit & Delete by Agent
# ============================================================


@patch("agentblog.app.main.httpx.AsyncClient")
def test_edit_own_post(mock_async_client, client):
    """Edit as posting agent, verify changes."""
    _create_post(mock_async_client, client, title="Original", body="Original body")

    mock_async_client.return_value = _mock_registry_success()
    resp = client.put(
        "/v1/posts/1",
        json={"title": "Updated Title", "body": "Updated body"},
        headers={"Authorization": "Bearer proof_test123"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == "Updated Title"
    assert data["body"] == "Updated body"
    assert data["updated_at"] is not None


@patch("agentblog.app.main.httpx.AsyncClient")
def test_edit_other_agents_post_forbidden(mock_async_client, client):
    """403 when trying to edit another agent's post."""
    _create_post(mock_async_client, client, title="Owner Post", agent_name="owner_bot")

    mock_async_client.return_value = _mock_registry_success("other_bot")
    resp = client.put(
        "/v1/posts/1",
        json={"title": "Hacked"},
        headers={"Authorization": "Bearer proof_test123"},
    )
    assert resp.status_code == 403


@patch("agentblog.app.main.httpx.AsyncClient")
def test_edit_post_not_found(mock_async_client, client):
    """404 when post doesn't exist."""
    mock_async_client.return_value = _mock_registry_success()
    resp = client.put(
        "/v1/posts/999",
        json={"title": "Ghost"},
        headers={"Authorization": "Bearer proof_test123"},
    )
    assert resp.status_code == 404


@patch("agentblog.app.main.httpx.AsyncClient")
def test_edit_post_partial_update(mock_async_client, client):
    """Only update title, body stays."""
    _create_post(mock_async_client, client, title="Original Title", body="Keep this body")

    mock_async_client.return_value = _mock_registry_success()
    resp = client.put(
        "/v1/posts/1",
        json={"title": "New Title"},
        headers={"Authorization": "Bearer proof_test123"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == "New Title"
    assert data["body"] == "Keep this body"


@patch("agentblog.app.main.httpx.AsyncClient")
def test_delete_own_post(mock_async_client, client):
    """204, post gone."""
    _create_post(mock_async_client, client, title="Delete Me")

    mock_async_client.return_value = _mock_registry_success()
    resp = client.delete("/v1/posts/1", headers={"Authorization": "Bearer proof_test123"})
    assert resp.status_code == 204

    # Verify post is gone
    mock_async_client.return_value = _mock_registry_success()
    resp = client.get("/v1/posts/1", headers={"Authorization": "Bearer proof_read"})
    assert resp.status_code == 404


@patch("agentblog.app.main.httpx.AsyncClient")
def test_delete_other_agents_post_forbidden(mock_async_client, client):
    """403 when trying to delete another agent's post."""
    _create_post(mock_async_client, client, title="Owner Post", agent_name="owner_bot")

    mock_async_client.return_value = _mock_registry_success("other_bot")
    resp = client.delete("/v1/posts/1", headers={"Authorization": "Bearer proof_test123"})
    assert resp.status_code == 403


@patch("agentblog.app.main.httpx.AsyncClient")
def test_delete_post_not_found(mock_async_client, client):
    """404 when post doesn't exist."""
    mock_async_client.return_value = _mock_registry_success()
    resp = client.delete("/v1/posts/999", headers={"Authorization": "Bearer proof_test123"})
    assert resp.status_code == 404


# ============================================================
# Phase 3: Comments
# ============================================================


@patch("agentblog.app.main.httpx.AsyncClient")
def test_create_comment(mock_async_client, client):
    """Comment on a post."""
    _create_post(mock_async_client, client, title="Post to comment on")

    mock_async_client.return_value = _mock_registry_success("commenter_bot", "I comment")
    resp = client.post(
        "/v1/posts/1/comments",
        json={"body": "Great post!"},
        headers={"Authorization": "Bearer proof_test123"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["body"] == "Great post!"
    assert data["agent_name"] == "commenter_bot"
    assert data["post_id"] == 1


@patch("agentblog.app.main.httpx.AsyncClient")
def test_create_comment_nonexistent_post(mock_async_client, client):
    """404 when post doesn't exist."""
    mock_async_client.return_value = _mock_registry_success()
    resp = client.post(
        "/v1/posts/999/comments",
        json={"body": "Hello?"},
        headers={"Authorization": "Bearer proof_test123"},
    )
    assert resp.status_code == 404


@patch("agentblog.app.main.httpx.AsyncClient")
def test_list_comments(mock_async_client, client):
    """Multiple comments, verify order."""
    _create_post(mock_async_client, client, title="Post")

    mock_async_client.return_value = _mock_registry_success("bot_a")
    client.post("/v1/posts/1/comments", json={"body": "First comment"},
                headers={"Authorization": "Bearer proof_a"})
    main.agent_comment_limiter.reset("bot_a")

    mock_async_client.return_value = _mock_registry_success("bot_b")
    client.post("/v1/posts/1/comments", json={"body": "Second comment"},
                headers={"Authorization": "Bearer proof_b"})

    mock_async_client.return_value = _mock_registry_success()
    resp = client.get("/v1/posts/1/comments", headers={"Authorization": "Bearer proof_read"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 2
    # Oldest first
    assert data["comments"][0]["body"] == "First comment"
    assert data["comments"][1]["body"] == "Second comment"


@patch("agentblog.app.main.httpx.AsyncClient")
def test_delete_own_comment(mock_async_client, client):
    """Delete own comment, verify gone."""
    _create_post(mock_async_client, client, title="Post")

    mock_async_client.return_value = _mock_registry_success("commenter")
    client.post("/v1/posts/1/comments", json={"body": "To delete"},
                headers={"Authorization": "Bearer proof_c"})

    mock_async_client.return_value = _mock_registry_success("commenter")
    resp = client.delete("/v1/posts/1/comments/1", headers={"Authorization": "Bearer proof_c"})
    assert resp.status_code == 204

    # Verify gone
    mock_async_client.return_value = _mock_registry_success()
    resp = client.get("/v1/posts/1/comments", headers={"Authorization": "Bearer proof_read"})
    assert resp.json()["count"] == 0


@patch("agentblog.app.main.httpx.AsyncClient")
def test_delete_other_agents_comment_forbidden(mock_async_client, client):
    """403 when trying to delete another agent's comment."""
    _create_post(mock_async_client, client, title="Post")

    mock_async_client.return_value = _mock_registry_success("author_bot")
    client.post("/v1/posts/1/comments", json={"body": "My comment"},
                headers={"Authorization": "Bearer proof_a"})

    mock_async_client.return_value = _mock_registry_success("other_bot")
    resp = client.delete("/v1/posts/1/comments/1", headers={"Authorization": "Bearer proof_b"})
    assert resp.status_code == 403


@patch("agentblog.app.main.httpx.AsyncClient")
def test_comment_body_too_long(mock_async_client, client):
    """422 when comment body exceeds max length."""
    _create_post(mock_async_client, client, title="Post")

    mock_async_client.return_value = _mock_registry_success()
    resp = client.post(
        "/v1/posts/1/comments",
        json={"body": "x" * 2001},
        headers={"Authorization": "Bearer proof_test123"},
    )
    assert resp.status_code == 422


@patch("agentblog.app.main.httpx.AsyncClient")
def test_comment_rate_limit(mock_async_client, client):
    """Verify comment cooldown."""
    _create_post(mock_async_client, client, title="Post")

    mock_async_client.return_value = _mock_registry_success("commenter")
    resp1 = client.post("/v1/posts/1/comments", json={"body": "First"},
                        headers={"Authorization": "Bearer proof_c"})
    assert resp1.status_code == 201

    # Second comment should be rate limited
    resp2 = client.post("/v1/posts/1/comments", json={"body": "Second"},
                        headers={"Authorization": "Bearer proof_c"})
    assert resp2.status_code == 429


@patch("agentblog.app.main.httpx.AsyncClient")
def test_comments_count_in_post_response(mock_async_client, client):
    """Verify comments_count in post detail."""
    _create_post(mock_async_client, client, title="Post")

    mock_async_client.return_value = _mock_registry_success("commenter")
    client.post("/v1/posts/1/comments", json={"body": "Comment 1"},
                headers={"Authorization": "Bearer proof_c"})

    mock_async_client.return_value = _mock_registry_success()
    resp = client.get("/v1/posts/1", headers={"Authorization": "Bearer proof_read"})
    assert resp.status_code == 200
    assert resp.json()["comments_count"] == 1
