"""Tests for AgentMessenger — direct messaging powered by AgentAuth."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from agentmessenger.app import main
from agentmessenger.app.main import app
from agentmessenger.app.store import MessengerStore

# Patch target for the SDK-based proof-token verification.
_VERIFY_PATCH = "agentmessenger.app.main._auth.verify_proof_token_via_registry_async"

# Patch target for the registry-backed recipient existence check.
_RECIPIENT_PATCH = "agentmessenger.app.main.recipient_exists"


@pytest.fixture(autouse=True)
def clean_state():
    """Fresh in-memory DB and reset all rate-limit / cache state for each test."""
    fresh = MessengerStore(db_path=":memory:")
    main.store = fresh
    main.pair_limiter.reset_all()
    main.global_limiter.reset_all()
    main.recipient_cache.clear()
    yield
    fresh.close()


@pytest.fixture
def client():
    return TestClient(app)


def _agent(name="alice", verified=False, description="A test agent"):
    """Shape returned by AgentAuth.verify_proof_token_via_registry_async."""
    return {"name": name, "description": description, "verified": verified, "active": True}


def _send(client, to="bob", body="hi", reply_to_id=None, sender="alice", verified=False):
    """Helper: send a message as `sender`, recipient assumed to exist."""
    with patch(_VERIFY_PATCH, new_callable=AsyncMock) as mv, \
         patch(_RECIPIENT_PATCH, new_callable=AsyncMock) as mr:
        mv.return_value = _agent(sender, verified=verified)
        mr.return_value = True
        payload = {"to": to, "body": body}
        if reply_to_id is not None:
            payload["reply_to_id"] = reply_to_id
        return client.post(
            "/v1/messages",
            json=payload,
            headers={"Authorization": "Bearer proof_test"},
        )


# --- Skill / onboarding endpoints ---


def test_root_landing_page(client):
    """Root serves a small descriptive HTML page (for SEO + agent discovery)
    rather than redirecting; messages themselves remain private."""
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    text = resp.text
    # Brand chrome + skill.md callout link (matches blog/board pattern)
    assert "AgentMessenger" in text
    assert 'href="/skill.md"' in text
    # SEO essentials
    assert '<meta name="description"' in text
    assert '<meta name="keywords"' in text
    assert '<meta name="robots" content="index, follow">' in text
    assert "og:title" in text
    # Discovery links to the rest of the skill suite
    assert 'href="/heartbeat.md"' in text
    assert 'href="/rules.md"' in text
    assert 'href="/skill.json"' in text


def test_landing_seo_phrases_present(client):
    """SEO discovery phrases that agents (or developers building agents) might
    search for must appear on the landing — title, body, keywords, FAQ."""
    text = client.get("/").text.lower()
    for phrase in [
        "messenger for ai agents",
        "messenger for autonomous agents",
        "whatsapp for ai agents",
        "email for ai agents",
        "agent to agent messaging",
        "how do ai agents communicate",
    ]:
        assert phrase in text, f"missing SEO phrase: {phrase!r}"


def test_landing_has_faq_jsonld(client):
    """FAQPage JSON-LD enables Google rich snippets in search results."""
    text = client.get("/").text
    assert 'application/ld+json' in text
    assert '"@type": "FAQPage"' in text
    assert '"@type": "Question"' in text


def test_skill_json_keywords_include_seo_phrases(client):
    """skill.json keywords drive agent-side discovery; must mirror landing SEO."""
    data = client.get("/skill.json").json()
    keywords = data["keywords"]
    for phrase in ["messenger for ai agents", "whatsapp for ai agents", "email for ai agents"]:
        assert phrase in keywords, f"missing keyword: {phrase!r}"
    triggers = data["agentauth"]["triggers"]
    assert "messenger for ai agents" in triggers
    assert "agent to agent messaging" in triggers


def test_skill_md(client):
    resp = client.get("/skill.md")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "text/markdown; charset=utf-8"
    text = resp.text
    assert "AgentMessenger" in text
    assert "curl" in text
    assert "reply_to_id" in text
    assert "/v1/messages/unread" in text


def test_heartbeat_md(client):
    resp = client.get("/heartbeat.md")
    assert resp.status_code == 200
    assert "Heartbeat" in resp.text
    assert "Step 1" in resp.text


def test_rules_md(client):
    resp = client.get("/rules.md")
    assert resp.status_code == 200
    assert "Community Rules" in resp.text
    assert "Be Genuine" in resp.text


def test_skill_json(client):
    resp = client.get("/skill.json")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/json"
    data = resp.json()
    assert data["name"] == "agentmessenger"
    assert data["agentauth"]["category"] == "messaging"
    assert data["agentauth"]["limits"]["body_max_length"] == 1024
    assert data["agentauth"]["behavior"]["auto_mark_read_on_unread_fetch"] is True
    assert "send_message" in data["agentauth"]["endpoints"]
    assert "agentloka.ai" in data["homepage"]


# --- Auth ---


def test_send_missing_auth(client):
    resp = client.post("/v1/messages", json={"to": "bob", "body": "hi"})
    assert resp.status_code == 401
    assert "agentloka.ai" in resp.json()["detail"]


@patch(_VERIFY_PATCH, new_callable=AsyncMock)
def test_send_invalid_token(mv, client):
    mv.return_value = None
    resp = client.post(
        "/v1/messages",
        json={"to": "bob", "body": "hi"},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 401
    assert "not verified" in resp.json()["detail"]


# --- Send: happy path ---


def test_send_happy_path(client):
    resp = _send(client, to="bob", body="hello bob", sender="alice")
    assert resp.status_code == 201
    data = resp.json()
    assert data["id"] == 1
    assert data["from_agent"] == "alice"
    assert data["to_agent"] == "bob"
    assert data["body"] == "hello bob"
    assert data["reply_to_id"] is None
    assert data["read_at"] is None


def test_send_sender_taken_from_token_not_body(client):
    """Sender can never be spoofed — it always comes from the verified token."""
    # The body has no sender field, but make sure the response uses the token's name.
    with patch(_VERIFY_PATCH, new_callable=AsyncMock) as mv, \
         patch(_RECIPIENT_PATCH, new_callable=AsyncMock) as mr:
        mv.return_value = _agent("real_sender")
        mr.return_value = True
        resp = client.post(
            "/v1/messages",
            json={"to": "bob", "body": "hi"},
            headers={"Authorization": "Bearer proof"},
        )
    assert resp.status_code == 201
    assert resp.json()["from_agent"] == "real_sender"


# --- Send: validation ---


def test_send_recipient_not_found(client):
    with patch(_VERIFY_PATCH, new_callable=AsyncMock) as mv, \
         patch(_RECIPIENT_PATCH, new_callable=AsyncMock) as mr:
        mv.return_value = _agent("alice")
        mr.return_value = False
        resp = client.post(
            "/v1/messages",
            json={"to": "ghost", "body": "anyone there?"},
            headers={"Authorization": "Bearer proof"},
        )
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert "ghost" in detail
    assert "/v1/agents/ghost" in detail


def test_send_body_too_long(client):
    with patch(_VERIFY_PATCH, new_callable=AsyncMock) as mv, \
         patch(_RECIPIENT_PATCH, new_callable=AsyncMock) as mr:
        mv.return_value = _agent("alice")
        mr.return_value = True
        resp = client.post(
            "/v1/messages",
            json={"to": "bob", "body": "x" * 1025},
            headers={"Authorization": "Bearer proof"},
        )
    assert resp.status_code == 422


def test_send_body_at_limit_ok(client):
    with patch(_VERIFY_PATCH, new_callable=AsyncMock) as mv, \
         patch(_RECIPIENT_PATCH, new_callable=AsyncMock) as mr:
        mv.return_value = _agent("alice")
        mr.return_value = True
        resp = client.post(
            "/v1/messages",
            json={"to": "bob", "body": "x" * 1024},
            headers={"Authorization": "Bearer proof"},
        )
    assert resp.status_code == 201


# --- Send: reply_to_id ---


def test_reply_to_existing_message(client):
    # alice sends bob a message
    _send(client, to="bob", body="original", sender="alice")
    # bob replies, referencing message id 1
    resp = _send(client, to="alice", body="reply", reply_to_id=1, sender="bob")
    assert resp.status_code == 201
    assert resp.json()["reply_to_id"] == 1


def test_reply_to_nonexistent_message(client):
    resp = _send(client, to="bob", body="ghost reply", reply_to_id=999, sender="alice")
    assert resp.status_code == 400
    assert "999" in resp.json()["detail"]


def test_reply_to_message_not_involving_sender(client):
    """Cannot reply to a message you neither sent nor received (prevents id-probing)."""
    # alice sends bob a private message
    _send(client, to="bob", body="private", sender="alice")
    # mallory tries to reply to message 1 (she is neither sender nor recipient)
    resp = _send(client, to="bob", body="snoopy reply", reply_to_id=1, sender="mallory")
    assert resp.status_code == 400
    assert "did not send or receive" in resp.json()["detail"]


# --- Send: rate limits ---


def test_pair_cooldown_unverified(client):
    """Unverified agent sending twice to the same recipient: second is 429."""
    r1 = _send(client, to="bob", body="first", sender="alice", verified=False)
    assert r1.status_code == 201
    r2 = _send(client, to="bob", body="second", sender="alice", verified=False)
    assert r2.status_code == 429
    assert r2.json()["retry_after"] > 0
    assert "Retry-After" in r2.headers


def test_pair_cooldown_independent_per_recipient(client):
    """Cooldown is per (sender, recipient) — different recipient is allowed."""
    r1 = _send(client, to="bob", body="hi bob", sender="alice")
    assert r1.status_code == 201
    r2 = _send(client, to="carol", body="hi carol", sender="alice")
    assert r2.status_code == 201


def test_global_hourly_cap_unverified(client):
    """Unverified agent gets cut off at 15 sends per hour."""
    # First 15 succeed (each to a different recipient to avoid pair cooldown)
    for i in range(15):
        r = _send(client, to=f"bob{i}", body="msg", sender="alice", verified=False)
        assert r.status_code == 201, f"send #{i+1} failed: {r.json()}"
    # 16th hits the hourly cap
    r = _send(client, to="bob_extra", body="too many", sender="alice", verified=False)
    assert r.status_code == 429
    assert "Hourly send limit" in r.json()["detail"]


# --- Unread fetch (auto-marks read) ---


def test_unread_returns_messages_addressed_to_caller(client):
    _send(client, to="bob", body="msg1", sender="alice")
    _send(client, to="bob", body="msg2", sender="carol")  # different sender, no pair conflict

    with patch(_VERIFY_PATCH, new_callable=AsyncMock) as mv:
        mv.return_value = _agent("bob")
        resp = client.get("/v1/messages/unread", headers={"Authorization": "Bearer proof"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 2
    assert data["total_count"] == 2
    bodies = [m["body"] for m in data["messages"]]
    assert bodies == ["msg1", "msg2"]  # oldest first


def test_unread_auto_marks_read(client):
    _send(client, to="bob", body="hello", sender="alice")

    with patch(_VERIFY_PATCH, new_callable=AsyncMock) as mv:
        mv.return_value = _agent("bob")
        # First fetch returns the message
        r1 = client.get("/v1/messages/unread", headers={"Authorization": "Bearer p"})
        assert r1.status_code == 200
        assert r1.json()["count"] == 1
        assert r1.json()["messages"][0]["read_at"] is not None
        # Second fetch is empty (auto-marked)
        r2 = client.get("/v1/messages/unread", headers={"Authorization": "Bearer p"})
        assert r2.status_code == 200
        assert r2.json()["count"] == 0


def test_unread_pagination(client):
    for i in range(3):
        _send(client, to="bob", body=f"m{i}", sender=f"sender{i}")
    with patch(_VERIFY_PATCH, new_callable=AsyncMock) as mv:
        mv.return_value = _agent("bob")
        r1 = client.get(
            "/v1/messages/unread?page=1&limit=2",
            headers={"Authorization": "Bearer p"},
        )
        assert r1.status_code == 200
        d1 = r1.json()
        assert d1["count"] == 2
        assert d1["total_count"] == 3
        # Next page returns the remaining 1
        r2 = client.get(
            "/v1/messages/unread?page=1&limit=2",
            headers={"Authorization": "Bearer p"},
        )
        d2 = r2.json()
        assert d2["count"] == 1


def test_unread_only_shows_messages_for_caller(client):
    _send(client, to="bob", body="for bob", sender="alice")
    _send(client, to="carol", body="for carol", sender="alice")

    with patch(_VERIFY_PATCH, new_callable=AsyncMock) as mv:
        mv.return_value = _agent("bob")
        resp = client.get("/v1/messages/unread", headers={"Authorization": "Bearer p"})
    bodies = [m["body"] for m in resp.json()["messages"]]
    assert bodies == ["for bob"]


# --- By-day fetch ---


def test_by_day_returns_received_messages(client):
    _send(client, to="bob", body="today", sender="alice")
    from datetime import UTC, datetime as _dt
    today = _dt.now(UTC).strftime("%Y-%m-%d")

    with patch(_VERIFY_PATCH, new_callable=AsyncMock) as mv:
        mv.return_value = _agent("bob")
        resp = client.get(
            f"/v1/messages/by-day?date={today}",
            headers={"Authorization": "Bearer p"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1
    assert data["messages"][0]["body"] == "today"


def test_by_day_does_not_mark_read(client):
    _send(client, to="bob", body="today", sender="alice")
    from datetime import UTC, datetime as _dt
    today = _dt.now(UTC).strftime("%Y-%m-%d")

    with patch(_VERIFY_PATCH, new_callable=AsyncMock) as mv:
        mv.return_value = _agent("bob")
        # by-day fetch
        r1 = client.get(
            f"/v1/messages/by-day?date={today}",
            headers={"Authorization": "Bearer p"},
        )
        assert r1.json()["messages"][0]["read_at"] is None
        # unread should still see it
        r2 = client.get("/v1/messages/unread", headers={"Authorization": "Bearer p"})
        assert r2.json()["count"] == 1


def test_by_day_invalid_date(client):
    with patch(_VERIFY_PATCH, new_callable=AsyncMock) as mv:
        mv.return_value = _agent("bob")
        resp = client.get(
            "/v1/messages/by-day?date=not-a-date",
            headers={"Authorization": "Bearer p"},
        )
    assert resp.status_code == 400
    assert "YYYY-MM-DD" in resp.json()["detail"]


# --- Sent outbox ---


def test_sent_lists_own_messages_only(client):
    _send(client, to="bob", body="from alice", sender="alice")
    _send(client, to="alice", body="from carol", sender="carol")

    with patch(_VERIFY_PATCH, new_callable=AsyncMock) as mv:
        mv.return_value = _agent("alice")
        resp = client.get("/v1/messages/sent", headers={"Authorization": "Bearer p"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1
    assert data["messages"][0]["body"] == "from alice"
    assert data["messages"][0]["from_agent"] == "alice"


def test_sent_pagination(client):
    for i in range(3):
        _send(client, to=f"bob{i}", body=f"m{i}", sender="alice")

    with patch(_VERIFY_PATCH, new_callable=AsyncMock) as mv:
        mv.return_value = _agent("alice")
        resp = client.get(
            "/v1/messages/sent?page=1&limit=2",
            headers={"Authorization": "Bearer p"},
        )
    data = resp.json()
    assert data["count"] == 2
    assert data["total_count"] == 3


# --- Single message lookup ---


def test_get_message_as_sender(client):
    _send(client, to="bob", body="hi", sender="alice")
    with patch(_VERIFY_PATCH, new_callable=AsyncMock) as mv:
        mv.return_value = _agent("alice")
        resp = client.get("/v1/messages/1", headers={"Authorization": "Bearer p"})
    assert resp.status_code == 200
    assert resp.json()["body"] == "hi"


def test_get_message_as_recipient(client):
    _send(client, to="bob", body="hi", sender="alice")
    with patch(_VERIFY_PATCH, new_callable=AsyncMock) as mv:
        mv.return_value = _agent("bob")
        resp = client.get("/v1/messages/1", headers={"Authorization": "Bearer p"})
    assert resp.status_code == 200


def test_get_message_third_party_forbidden(client):
    _send(client, to="bob", body="private", sender="alice")
    with patch(_VERIFY_PATCH, new_callable=AsyncMock) as mv:
        mv.return_value = _agent("mallory")
        resp = client.get("/v1/messages/1", headers={"Authorization": "Bearer p"})
    assert resp.status_code == 403


def test_get_message_not_found(client):
    with patch(_VERIFY_PATCH, new_callable=AsyncMock) as mv:
        mv.return_value = _agent("alice")
        resp = client.get("/v1/messages/999", headers={"Authorization": "Bearer p"})
    assert resp.status_code == 404


# --- Self-send is allowed ---


def test_self_send_allowed(client):
    """Plan: self-send is acceptable (no special handling)."""
    with patch(_VERIFY_PATCH, new_callable=AsyncMock) as mv, \
         patch(_RECIPIENT_PATCH, new_callable=AsyncMock) as mr:
        mv.return_value = _agent("alice")
        mr.return_value = True
        resp = client.post(
            "/v1/messages",
            json={"to": "alice", "body": "note to self"},
            headers={"Authorization": "Bearer p"},
        )
    assert resp.status_code == 201
    data = resp.json()
    assert data["from_agent"] == "alice"
    assert data["to_agent"] == "alice"
