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


def _register_platform(client, name="test_plat", domain="test.example.com", email=None):
    payload = {"name": name, "domain": domain}
    if email is not None:
        payload["email"] = email
    return client.post("/v1/platforms/register", json=payload)


def _platform_key(resp):
    """Extract platform_secret_key from platform registration response."""
    return resp.json()["platform_secret_key"]


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


# --- Platform registration ---


def test_register_platform(client):
    resp = _register_platform(client)
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "test_plat"
    assert data["domain"] == "test.example.com"
    assert data["platform_secret_key"].startswith("platauth_")
    assert data["active"] is True
    assert data["verified"] is False
    assert data["important"] is not None


def test_register_platform_with_description(client):
    resp = client.post("/v1/platforms/register", json={
        "name": "desc_plat",
        "domain": "desc.example.com",
        "description": "A platform for testing",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["description"] == "A platform for testing"


def test_register_platform_description_too_long(client):
    resp = client.post("/v1/platforms/register", json={
        "name": "long_plat",
        "domain": "long.example.com",
        "description": "x" * 141,
    })
    assert resp.status_code == 422
    assert "140" in resp.json()["detail"]


def test_register_platform_duplicate(client):
    _register_platform(client, "taken_plat")
    resp = _register_platform(client, "taken_plat")
    assert resp.status_code == 409


def test_register_platform_invalid_name(client):
    resp = _register_platform(client, "Bad-Name")
    assert resp.status_code == 422


def test_get_platform(client):
    _register_platform(client, "lookup_plat")
    resp = client.get("/v1/platforms/lookup_plat")
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "lookup_plat"
    assert data["platform_secret_key"] is None  # Never exposed on public lookup


def test_get_platform_not_found(client):
    resp = client.get("/v1/platforms/ghost_plat")
    assert resp.status_code == 404


def test_revoke_platform(client):
    resp = _register_platform(client, "doomed_plat")
    key = _platform_key(resp)

    del_resp = client.delete("/v1/platforms/doomed_plat", headers={"Authorization": f"Bearer {key}"})
    assert del_resp.status_code == 200
    assert del_resp.json()["revoked"] is True

    assert client.get("/v1/platforms/doomed_plat").status_code == 404


def test_revoke_platform_wrong_key(client):
    _register_platform(client, "safe_plat")
    resp = client.delete("/v1/platforms/safe_plat", headers={"Authorization": "Bearer platauth_wrong"})
    assert resp.status_code == 403


def test_list_platforms(client):
    _register_platform(client, "plat_a", domain="a.example.com")
    _register_platform(client, "plat_b", domain="b.example.com")
    resp = client.get("/v1/platforms")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 2
    names = {p["name"] for p in data["platforms"]}
    assert names == {"plat_a", "plat_b"}
    for p in data["platforms"]:
        assert p["platform_secret_key"] is None


def test_list_platforms_empty(client):
    resp = client.get("/v1/platforms")
    assert resp.status_code == 200
    assert resp.json()["count"] == 0


def test_platform_description_in_lookup(client):
    client.post("/v1/platforms/register", json={
        "name": "info_plat",
        "domain": "info.example.com",
        "description": "An info platform",
    })
    resp = client.get("/v1/platforms/info_plat")
    assert resp.json()["description"] == "An info platform"


def test_platform_email_verification(client, store):
    resp = _register_platform(client, "email_plat", email="admin@example.com")
    assert resp.status_code == 201

    token = store.get_platform_pending_verification_token("email_plat")
    assert token is not None

    verify_resp = client.get(f"/v1/verify-platform/{token}")
    assert verify_resp.status_code == 200
    assert "email_plat" in verify_resp.text

    platform = client.get("/v1/platforms/email_plat").json()
    assert platform["verified"] is True


def test_registered_platform_gets_higher_rate_limit(client):
    """Registered platform with platauth_ Bearer should get 300/min, not 30/min."""
    resp = _register_platform(client, "fast_plat")
    key = _platform_key(resp)

    # Send 31 requests — should not get rate limited (30/min is anonymous limit)
    for _ in range(31):
        r = client.get(
            "/v1/verify-proof/fake_token",
            headers={"Authorization": f"Bearer {key}"},
        )
        assert r.status_code != 429  # 401 (invalid token) is fine


# --- Agent reports ---


def test_platform_reports_agent(client):
    _register(client, "bad_bot")
    resp = _register_platform(client, "reporter_plat")
    key = _platform_key(resp)

    report_resp = client.post(
        "/v1/agents/bad_bot/reports",
        headers={"Authorization": f"Bearer {key}"},
    )
    assert report_resp.status_code == 201
    assert report_resp.json()["reported"] is True


def test_platform_reports_agent_duplicate(client):
    _register(client, "bad_bot")
    resp = _register_platform(client, "reporter_plat")
    key = _platform_key(resp)

    client.post("/v1/agents/bad_bot/reports", headers={"Authorization": f"Bearer {key}"})
    dup_resp = client.post("/v1/agents/bad_bot/reports", headers={"Authorization": f"Bearer {key}"})
    assert dup_resp.status_code == 409


def test_different_platforms_report_same_agent(client):
    _register(client, "bad_bot")
    key_a = _platform_key(_register_platform(client, "plat_a"))
    key_b = _platform_key(_register_platform(client, "plat_b"))

    assert client.post("/v1/agents/bad_bot/reports", headers={"Authorization": f"Bearer {key_a}"}).status_code == 201
    assert client.post("/v1/agents/bad_bot/reports", headers={"Authorization": f"Bearer {key_b}"}).status_code == 201


def test_get_agent_reports(client):
    _register(client, "reported_bot")
    key_a = _platform_key(_register_platform(client, "plat_a"))
    key_b = _platform_key(_register_platform(client, "plat_b"))

    client.post("/v1/agents/reported_bot/reports", headers={"Authorization": f"Bearer {key_a}"})
    client.post("/v1/agents/reported_bot/reports", headers={"Authorization": f"Bearer {key_b}"})

    resp = client.get("/v1/agents/reported_bot/reports")
    assert resp.status_code == 200
    data = resp.json()
    assert data["report_count"] == 2
    assert set(data["reporting_platforms"]) == {"plat_a", "plat_b"}


def test_retract_report(client):
    _register(client, "bad_bot")
    key = _platform_key(_register_platform(client, "plat_a"))

    client.post("/v1/agents/bad_bot/reports", headers={"Authorization": f"Bearer {key}"})

    retract_resp = client.delete("/v1/agents/bad_bot/reports", headers={"Authorization": f"Bearer {key}"})
    assert retract_resp.status_code == 204

    reports = client.get("/v1/agents/bad_bot/reports").json()
    assert reports["report_count"] == 0


def test_retract_nonexistent_report(client):
    _register(client, "good_bot")
    key = _platform_key(_register_platform(client, "plat_a"))

    resp = client.delete("/v1/agents/good_bot/reports", headers={"Authorization": f"Bearer {key}"})
    assert resp.status_code == 404


def test_report_agent_unauthenticated(client):
    _register(client, "target_bot")
    resp = client.post("/v1/agents/target_bot/reports")
    assert resp.status_code == 401


def test_report_nonexistent_agent(client):
    key = _platform_key(_register_platform(client, "plat_a"))
    resp = client.post("/v1/agents/ghost_bot/reports", headers={"Authorization": f"Bearer {key}"})
    assert resp.status_code == 404


def test_revoke_platform_cascades_reports(client):
    """When a platform is revoked, its reports are cascade-deleted."""
    _register(client, "bad_bot")
    resp = _register_platform(client, "temp_plat")
    key = _platform_key(resp)

    client.post("/v1/agents/bad_bot/reports", headers={"Authorization": f"Bearer {key}"})
    assert client.get("/v1/agents/bad_bot/reports").json()["report_count"] == 1

    client.delete("/v1/platforms/temp_plat", headers={"Authorization": f"Bearer {key}"})
    assert client.get("/v1/agents/bad_bot/reports").json()["report_count"] == 0


# --- Report count on agent profile ---


def test_agent_profile_includes_report_count(client):
    """GET /v1/agents/{name} includes report_count and reporting_platforms."""
    _register(client, "reported_bot")
    key = _platform_key(_register_platform(client, "plat_a"))
    client.post("/v1/agents/reported_bot/reports", headers={"Authorization": f"Bearer {key}"})

    resp = client.get("/v1/agents/reported_bot")
    data = resp.json()
    assert data["report_count"] == 1
    assert data["reporting_platforms"] == ["plat_a"]


def test_agent_profile_no_reports(client):
    """Agent with no reports shows report_count: 0."""
    _register(client, "clean_bot")
    resp = client.get("/v1/agents/clean_bot")
    data = resp.json()
    assert data["report_count"] == 0
    assert data["reporting_platforms"] == []


def test_verify_proof_does_not_include_reports(client):
    """verify-proof response should NOT include report fields (hot path)."""
    resp = _register(client, "test_bot")
    proof_token = resp.json()["platform_proof_token"]

    verify_resp = client.get(f"/v1/verify-proof/{proof_token}")
    data = verify_resp.json()
    assert "report_count" not in data
    assert "reporting_platforms" not in data


def test_platform_md_page(client):
    resp = client.get("/platform.md")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "text/markdown; charset=utf-8"
    assert "platauth_" in resp.text
    assert "Platform" in resp.text


# --- Admin reporting ---

ADMIN_TOKEN = "test_admin_secret_token"


# --- Rate limiting on verify-proof ---


def test_verify_proof_rate_limit_allows_30(client):
    """30 requests within a minute should all succeed (not 429)."""
    for _ in range(30):
        resp = client.get("/v1/verify-proof/fake_token")
        assert resp.status_code != 429  # 401 (invalid token) is expected


def test_verify_proof_rate_limit_blocks_31st(client):
    """31st request should return 429 with platform registration nudge."""
    for _ in range(30):
        client.get("/v1/verify-proof/fake_token")

    resp = client.get("/v1/verify-proof/fake_token")
    assert resp.status_code == 429
    assert "/v1/platforms/register" in resp.json()["detail"]


def test_other_endpoints_not_rate_limited(client):
    """Other endpoints like /v1/agents should not be rate limited."""
    for _ in range(50):
        resp = client.get("/v1/agents")
        assert resp.status_code == 200


def test_admin_stats_disabled_when_no_token(client):
    resp = client.get("/v1/admin/stats")
    assert resp.status_code == 503


def test_admin_stats_missing_auth(client, monkeypatch):
    monkeypatch.setenv("AGENTAUTH_ADMIN_TOKEN", ADMIN_TOKEN)
    resp = client.get("/v1/admin/stats")
    assert resp.status_code == 401


def test_admin_stats_wrong_token(client, monkeypatch):
    monkeypatch.setenv("AGENTAUTH_ADMIN_TOKEN", ADMIN_TOKEN)
    resp = client.get("/v1/admin/stats", headers={"Authorization": "Bearer wrong"})
    assert resp.status_code == 403


def test_admin_stats(client, store, monkeypatch):
    monkeypatch.setenv("AGENTAUTH_ADMIN_TOKEN", ADMIN_TOKEN)
    _register(client, "bot_a", email="a@example.com")
    _register(client, "bot_b")

    # Verify one agent
    token = store.get_pending_verification_token("bot_a")
    client.get(f"/v1/verify/{token}")

    resp = client.get("/v1/admin/stats", headers={"Authorization": f"Bearer {ADMIN_TOKEN}"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert data["active"] == 2
    assert data["verified"] == 1
    assert data["unverified"] == 1
    assert data["pending_verifications"] == 0
    assert data["registrations_last_7d"] == 2
    assert data["registrations_last_30d"] == 2
    assert data["newest_agent"]["name"] in ("bot_a", "bot_b")
    assert "registrations_in_range" not in data  # No date filter


def test_admin_stats_date_filter(client, monkeypatch):
    monkeypatch.setenv("AGENTAUTH_ADMIN_TOKEN", ADMIN_TOKEN)
    _register(client, "dated_bot")

    resp = client.get(
        "/v1/admin/stats?from=2020-01-01&to=2099-12-31",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["registrations_in_range"] == 1
    assert data["range_from"] == "2020-01-01"
    assert data["range_to"] == "2099-12-31"


def test_admin_stats_includes_platform_counts(client, store, monkeypatch):
    monkeypatch.setenv("AGENTAUTH_ADMIN_TOKEN", ADMIN_TOKEN)
    _register(client, "bot_a")
    _register_platform(client, "plat_a", email="a@example.com")
    _register_platform(client, "plat_b")

    # Verify one platform
    token = store.get_platform_pending_verification_token("plat_a")
    client.get(f"/v1/verify-platform/{token}")

    resp = client.get("/v1/admin/stats", headers={"Authorization": f"Bearer {ADMIN_TOKEN}"})
    data = resp.json()
    assert data["platforms_total"] == 2
    assert data["platforms_active"] == 2
    assert data["platforms_verified"] == 1


def test_admin_stats_html(client, monkeypatch):
    monkeypatch.setenv("AGENTAUTH_ADMIN_TOKEN", ADMIN_TOKEN)
    _register(client, "html_bot")
    resp = client.get(
        "/v1/admin/stats?format=html",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "AgentAuth Admin" in resp.text
