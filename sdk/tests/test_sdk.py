"""Tests for the AgentAuth SDK client — flat identity model."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

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
