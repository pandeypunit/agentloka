"""Tests for the AgentAuth SDK client — flat identity model."""

import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PublicFormat,
)

from agentauth.client import AgentAuth


@pytest.fixture
def tmp_config(tmp_path):
    return tmp_path / "agentauth"


@pytest.fixture
def auth(tmp_config):
    return AgentAuth(registry_url="http://test:8000", config_dir=tmp_config)


# --- Credential storage ---


def test_credentials_path_creates_dir(auth, tmp_config):
    path = auth._credentials_path("my_bot")
    assert path == tmp_config / "credentials" / "my_bot.json"
    assert path.parent.exists()


# --- Register ---


@patch("agentauth.client.httpx.post")
def test_register_saves_credentials(mock_post, auth, tmp_config):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "name": "test_bot",
        "registry_secret_key": "agentauth_abc123",
        "platform_proof_token": "eyJhbGci...",
        "platform_proof_token_expires_in_seconds": 300,
        "active": True,
    }
    mock_resp.raise_for_status = MagicMock()
    mock_post.return_value = mock_resp

    result = auth.register("test_bot", description="A bot")

    assert result["registry_secret_key"] == "agentauth_abc123"
    assert result["platform_proof_token"] == "eyJhbGci..."
    assert result["platform_proof_token_expires_in_seconds"] == 300
    mock_post.assert_called_once_with(
        "http://test:8000/v1/agents/register",
        json={"name": "test_bot", "description": "A bot"},
    )

    # Credentials saved locally
    creds_file = tmp_config / "credentials" / "test_bot.json"
    assert creds_file.exists()
    saved = json.loads(creds_file.read_text())
    assert saved["name"] == "test_bot"
    assert saved["registry_secret_key"] == "agentauth_abc123"

    # File permissions
    assert oct(creds_file.stat().st_mode)[-3:] == "600"


@patch("agentauth.client.httpx.post")
def test_register_with_email(mock_post, auth, tmp_config):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "name": "email_bot",
        "registry_secret_key": "agentauth_abc123",
        "platform_proof_token": "eyJhbGci...",
        "platform_proof_token_expires_in_seconds": 300,
        "verified": False,
        "active": True,
    }
    mock_resp.raise_for_status = MagicMock()
    mock_post.return_value = mock_resp

    result = auth.register("email_bot", description="A bot", email="bot@example.com")

    assert result["verified"] is False
    mock_post.assert_called_once_with(
        "http://test:8000/v1/agents/register",
        json={"name": "email_bot", "description": "A bot", "email": "bot@example.com"},
    )


# --- Link email ---


@patch("agentauth.client.httpx.post")
def test_link_email(mock_post, auth, tmp_config):
    # Set up credentials
    creds_dir = tmp_config / "credentials"
    creds_dir.mkdir(parents=True)
    (creds_dir / "bot.json").write_text(
        json.dumps({"name": "bot", "registry_secret_key": "agentauth_key1"})
    )

    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "agent_name": "bot",
        "message": "Verification email sent. Check your inbox.",
    }
    mock_resp.raise_for_status = MagicMock()
    mock_post.return_value = mock_resp

    result = auth.link_email("bot", "owner@example.com")

    assert result["agent_name"] == "bot"
    mock_post.assert_called_once_with(
        "http://test:8000/v1/agents/me/email",
        json={"email": "owner@example.com"},
        headers={"Authorization": "Bearer agentauth_key1"},
    )


# --- Load credentials ---


def test_load_credentials(auth, tmp_config):
    creds_dir = tmp_config / "credentials"
    creds_dir.mkdir(parents=True)
    creds_file = creds_dir / "my_bot.json"
    creds_file.write_text(json.dumps({"name": "my_bot", "registry_secret_key": "agentauth_xyz"}))

    creds = auth.load_credentials("my_bot")
    assert creds["registry_secret_key"] == "agentauth_xyz"


def test_load_credentials_not_found(auth):
    with pytest.raises(FileNotFoundError, match="No credentials found"):
        auth.load_credentials("ghost_bot")


# --- Get registry secret key ---


def test_get_registry_secret_key(auth, tmp_config):
    creds_dir = tmp_config / "credentials"
    creds_dir.mkdir(parents=True)
    (creds_dir / "bot.json").write_text(
        json.dumps({"name": "bot", "registry_secret_key": "agentauth_key1"})
    )
    assert auth.get_registry_secret_key("bot") == "agentauth_key1"


# --- Auth headers ---


def test_registry_auth_headers(auth, tmp_config):
    creds_dir = tmp_config / "credentials"
    creds_dir.mkdir(parents=True)
    (creds_dir / "bot.json").write_text(
        json.dumps({"name": "bot", "registry_secret_key": "agentauth_key1"})
    )
    headers = auth.registry_auth_headers("bot")
    assert headers == {"Authorization": "Bearer agentauth_key1"}


# --- Proof tokens ---


@patch("agentauth.client.httpx.post")
def test_get_platform_proof_token(mock_post, auth, tmp_config):
    creds_dir = tmp_config / "credentials"
    creds_dir.mkdir(parents=True)
    (creds_dir / "bot.json").write_text(
        json.dumps({"name": "bot", "registry_secret_key": "agentauth_key1"})
    )

    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "platform_proof_token": "eyJhbGci_abc123",
        "agent_name": "bot",
        "expires_in_seconds": 300,
    }
    mock_resp.raise_for_status = MagicMock()
    mock_post.return_value = mock_resp

    token = auth.get_platform_proof_token("bot")
    assert token == "eyJhbGci_abc123"
    mock_post.assert_called_once_with(
        "http://test:8000/v1/agents/me/proof",
        headers={"Authorization": "Bearer agentauth_key1"},
    )


@patch("agentauth.client.httpx.post")
def test_platform_proof_headers(mock_post, auth, tmp_config):
    creds_dir = tmp_config / "credentials"
    creds_dir.mkdir(parents=True)
    (creds_dir / "bot.json").write_text(
        json.dumps({"name": "bot", "registry_secret_key": "agentauth_key1"})
    )

    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "platform_proof_token": "eyJhbGci_xyz789",
        "agent_name": "bot",
        "expires_in_seconds": 300,
    }
    mock_resp.raise_for_status = MagicMock()
    mock_post.return_value = mock_resp

    headers = auth.platform_proof_headers("bot")
    assert headers == {"Authorization": "Bearer eyJhbGci_xyz789"}


# --- Get me ---


@patch("agentauth.client.httpx.get")
def test_get_me(mock_get, auth, tmp_config):
    creds_dir = tmp_config / "credentials"
    creds_dir.mkdir(parents=True)
    (creds_dir / "bot.json").write_text(
        json.dumps({"name": "bot", "registry_secret_key": "agentauth_key1"})
    )

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"name": "bot", "active": True}
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    result = auth.get_me("bot")
    assert result["name"] == "bot"
    mock_get.assert_called_once_with(
        "http://test:8000/v1/agents/me",
        headers={"Authorization": "Bearer agentauth_key1"},
    )


# --- Get agent (public) ---


@patch("agentauth.client.httpx.get")
def test_get_agent(mock_get, auth):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"name": "other_bot", "active": True}
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    result = auth.get_agent("other_bot")
    assert result["name"] == "other_bot"
    mock_get.assert_called_once_with("http://test:8000/v1/agents/other_bot")


# --- List agents ---


def test_list_agents_empty(auth):
    assert auth.list_agents() == []


def test_list_agents(auth, tmp_config):
    creds_dir = tmp_config / "credentials"
    creds_dir.mkdir(parents=True)
    (creds_dir / "alpha.json").write_text(
        json.dumps({"name": "alpha", "registry_secret_key": "agentauth_a"})
    )
    (creds_dir / "beta.json").write_text(
        json.dumps({"name": "beta", "registry_secret_key": "agentauth_b"})
    )

    agents = auth.list_agents()
    assert len(agents) == 2
    names = {a["name"] for a in agents}
    assert names == {"alpha", "beta"}


# --- Revoke ---


@patch("agentauth.client.httpx.delete")
def test_revoke_success(mock_delete, auth, tmp_config):
    creds_dir = tmp_config / "credentials"
    creds_dir.mkdir(parents=True)
    creds_file = creds_dir / "bot.json"
    creds_file.write_text(json.dumps({"name": "bot", "registry_secret_key": "agentauth_key1"}))

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_delete.return_value = mock_resp

    assert auth.revoke("bot") is True
    assert not creds_file.exists()


@patch("agentauth.client.httpx.delete")
def test_revoke_wrong_key(mock_delete, auth, tmp_config):
    creds_dir = tmp_config / "credentials"
    creds_dir.mkdir(parents=True)
    creds_file = creds_dir / "bot.json"
    creds_file.write_text(json.dumps({"name": "bot", "registry_secret_key": "agentauth_wrong"}))

    mock_resp = MagicMock()
    mock_resp.status_code = 403
    mock_delete.return_value = mock_resp

    assert auth.revoke("bot") is False
    assert not creds_file.exists()  # Local creds still cleaned up


def test_revoke_not_registered(auth):
    with pytest.raises(FileNotFoundError):
        auth.revoke("ghost_bot")


# --- Platform-side token verification ---


@pytest.fixture
def ec_keypair():
    """Generate a test ECDSA P-256 keypair."""
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_pem = private_key.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo).decode()
    return private_key, public_pem


@patch("agentauth.client.httpx.get")
def test_get_public_key(mock_get, auth, ec_keypair):
    _, public_pem = ec_keypair
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"public_key_pem": public_pem}
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    key = auth.get_public_key()
    assert key == public_pem
    mock_get.assert_called_once_with("http://test:8000/.well-known/jwks.json")


@patch("agentauth.client.httpx.get")
def test_get_public_key_cached(mock_get, auth, ec_keypair):
    _, public_pem = ec_keypair
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"public_key_pem": public_pem}
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    auth.get_public_key()
    auth.get_public_key()
    assert mock_get.call_count == 1  # Only one HTTP call


@patch("agentauth.client.httpx.get")
def test_verify_proof_token_valid(mock_get, auth, ec_keypair):
    private_key, public_pem = ec_keypair
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"public_key_pem": public_pem}
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    token = jwt.encode(
        {"sub": "test_bot", "description": "A bot", "verified": False, "exp": int(time.time()) + 300},
        private_key,
        algorithm="ES256",
    )

    result = auth.verify_proof_token(token)
    assert result is not None
    assert result["sub"] == "test_bot"
    assert result["description"] == "A bot"


@patch("agentauth.client.httpx.get")
def test_verify_proof_token_expired(mock_get, auth, ec_keypair):
    private_key, public_pem = ec_keypair
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"public_key_pem": public_pem}
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    token = jwt.encode(
        {"sub": "test_bot", "exp": int(time.time()) - 60},
        private_key,
        algorithm="ES256",
    )

    assert auth.verify_proof_token(token) is None


def test_verify_proof_token_invalid(auth):
    auth._public_key_pem = "-----BEGIN PUBLIC KEY-----\nMFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAE\n-----END PUBLIC KEY-----"
    assert auth.verify_proof_token("garbage.token.here") is None


@patch("agentauth.client.httpx.get")
def test_verify_proof_token_via_registry(mock_get, auth):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "name": "test_bot",
        "description": "A bot",
        "verified": False,
        "active": True,
    }
    mock_get.return_value = mock_resp

    result = auth.verify_proof_token_via_registry("eyJhbGci_token123")
    assert result["name"] == "test_bot"
    mock_get.assert_called_once_with(
        "http://test:8000/v1/verify-proof/eyJhbGci_token123", headers={}
    )


@patch("agentauth.client.httpx.get")
def test_verify_proof_token_via_registry_invalid(mock_get, auth):
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_get.return_value = mock_resp

    assert auth.verify_proof_token_via_registry("bad_token") is None


@patch("agentauth.client.httpx.get")
def test_verify_proof_token_via_registry_with_platform_key(mock_get, auth):
    """Sync verify sends platform_secret_key as Bearer auth for higher rate limit."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"name": "test_bot", "active": True}
    mock_get.return_value = mock_resp

    result = auth.verify_proof_token_via_registry(
        "eyJhbGci_token123", platform_secret_key="platauth_abc123"
    )
    assert result["name"] == "test_bot"
    mock_get.assert_called_once_with(
        "http://test:8000/v1/verify-proof/eyJhbGci_token123",
        headers={"Authorization": "Bearer platauth_abc123"},
    )


# --- Async verify via registry ---


@pytest.mark.asyncio
async def test_verify_proof_token_via_registry_async(auth):
    """Async verify — valid token returns dict."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "name": "test_bot",
        "description": "A bot",
        "verified": False,
        "active": True,
    }

    with patch("agentauth.client.httpx.AsyncClient") as MockAsyncClient:
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__.return_value = mock_client
        MockAsyncClient.return_value = mock_client

        result = await auth.verify_proof_token_via_registry_async("eyJhbGci_token123")
        assert result["name"] == "test_bot"
        mock_client.get.assert_called_once_with(
            "http://test:8000/v1/verify-proof/eyJhbGci_token123", headers={}
        )


@pytest.mark.asyncio
async def test_verify_proof_token_via_registry_async_invalid(auth):
    """Async verify — invalid token returns None."""
    mock_resp = MagicMock()
    mock_resp.status_code = 401

    with patch("agentauth.client.httpx.AsyncClient") as MockAsyncClient:
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__.return_value = mock_client
        MockAsyncClient.return_value = mock_client

        assert await auth.verify_proof_token_via_registry_async("bad_token") is None


@pytest.mark.asyncio
async def test_verify_proof_token_via_registry_async_with_platform_key(auth):
    """Async verify sends platform_secret_key as Bearer auth for higher rate limit."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"name": "test_bot", "active": True}

    with patch("agentauth.client.httpx.AsyncClient") as MockAsyncClient:
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__.return_value = mock_client
        MockAsyncClient.return_value = mock_client

        result = await auth.verify_proof_token_via_registry_async(
            "eyJhbGci_token123", platform_secret_key="platauth_abc123"
        )
        assert result["name"] == "test_bot"
        mock_client.get.assert_called_once_with(
            "http://test:8000/v1/verify-proof/eyJhbGci_token123",
            headers={"Authorization": "Bearer platauth_abc123"},
        )


# --- Platform registration SDK ---


@patch("agentauth.client.httpx.post")
def test_register_platform(mock_post, auth, tmp_config):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "name": "test_plat",
        "domain": "test.example.com",
        "platform_secret_key": "platauth_abc123",
        "active": True,
    }
    mock_resp.raise_for_status = MagicMock()
    mock_post.return_value = mock_resp

    result = auth.register_platform("test_plat", domain="test.example.com")

    assert result["platform_secret_key"] == "platauth_abc123"
    mock_post.assert_called_once_with(
        "http://test:8000/v1/platforms/register",
        json={"name": "test_plat", "domain": "test.example.com"},
    )

    # Credentials saved
    creds_file = tmp_config / "platforms" / "test_plat.json"
    assert creds_file.exists()
    saved = json.loads(creds_file.read_text())
    assert saved["platform_secret_key"] == "platauth_abc123"
    assert oct(creds_file.stat().st_mode)[-3:] == "600"


@patch("agentauth.client.httpx.get")
def test_get_platform(mock_get, auth):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"name": "test_plat", "domain": "test.example.com", "active": True}
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    result = auth.get_platform("test_plat")
    assert result["name"] == "test_plat"
    mock_get.assert_called_once_with("http://test:8000/v1/platforms/test_plat")


@patch("agentauth.client.httpx.delete")
def test_revoke_platform(mock_delete, auth, tmp_config):
    plat_dir = tmp_config / "platforms"
    plat_dir.mkdir(parents=True)
    creds_file = plat_dir / "test_plat.json"
    creds_file.write_text(json.dumps({"name": "test_plat", "platform_secret_key": "platauth_key1"}))

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_delete.return_value = mock_resp

    assert auth.revoke_platform("test_plat") is True
    assert not creds_file.exists()


# --- Agent reporting SDK ---


@patch("agentauth.client.httpx.post")
def test_report_agent(mock_post, auth):
    mock_resp = MagicMock()
    mock_resp.status_code = 201
    mock_resp.raise_for_status = MagicMock()
    mock_post.return_value = mock_resp

    assert auth.report_agent("platauth_key1", "bad_bot") is True
    mock_post.assert_called_once_with(
        "http://test:8000/v1/agents/bad_bot/reports",
        headers={"Authorization": "Bearer platauth_key1"},
    )


@patch("agentauth.client.httpx.post")
def test_report_agent_duplicate(mock_post, auth):
    mock_resp = MagicMock()
    mock_resp.status_code = 409
    mock_post.return_value = mock_resp

    assert auth.report_agent("platauth_key1", "bad_bot") is False


@patch("agentauth.client.httpx.delete")
def test_retract_report(mock_delete, auth):
    mock_resp = MagicMock()
    mock_resp.status_code = 204
    mock_resp.raise_for_status = MagicMock()
    mock_delete.return_value = mock_resp

    assert auth.retract_report("platauth_key1", "bad_bot") is True


@patch("agentauth.client.httpx.delete")
def test_retract_report_not_found(mock_delete, auth):
    mock_resp = MagicMock()
    mock_resp.status_code = 404
    mock_delete.return_value = mock_resp

    assert auth.retract_report("platauth_key1", "good_bot") is False


@patch("agentauth.client.httpx.get")
def test_get_agent_reports(mock_get, auth):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "agent_name": "bad_bot",
        "report_count": 2,
        "reporting_platforms": ["plat_a", "plat_b"],
    }
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    result = auth.get_agent_reports("bad_bot")
    assert result["report_count"] == 2
    mock_get.assert_called_once_with("http://test:8000/v1/agents/bad_bot/reports")
