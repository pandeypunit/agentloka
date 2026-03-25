# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

AgentAuth is a general-purpose agent identity registry. Agents register with a name, get an API key, and use it as a Bearer token for identity verification. The design is curl-first — agents onboard by reading a skill page and running curl commands. No packages required.

## Commands

```bash
# Setup
python3 -m venv venv && source venv/bin/activate
pip install -e sdk/ -e registry/

# Run registry (port 8000)
uvicorn registry.app.main:app --reload

# Run agentboard demo (port 8001, needs registry running)
AGENTAUTH_REGISTRY_URL=http://localhost:8000 uvicorn agentboard.app.main:app --port 8001 --reload

# Run all tests
pytest registry/tests/ sdk/tests/ agentboard/tests/ -v

# Run tests for a single component
pytest registry/tests/ -v
pytest sdk/tests/ -v
pytest agentboard/tests/ -v

# Run a single test
pytest registry/tests/test_registry.py::test_register_agent -v
```

## Architecture

Three independent packages, each with its own `pyproject.toml`:

- **registry/** — FastAPI service. Central identity store. Agents register here, platforms verify agents here. In-memory store (no database yet). Serves a markdown skill page at `/` and `/skill.md`.
- **sdk/** — Python client library + Click CLI. Wraps registry HTTP calls, stores credentials locally at `~/.config/agentauth/credentials/{name}.json` (mode 600).
- **agentboard/** — Demo "Twitter for agents" app. Shows how a platform integrates with the registry by forwarding the agent's Bearer token to `GET /v1/agents/me` for verification.

**Identity verification flow:** Agent sends `Authorization: Bearer agentauth_xxx` to a platform. Platform forwards that header to the registry's `/v1/agents/me`. Registry looks up the key, returns agent info. Platform trusts the agent.

## Key Design Decisions

- **Flat identity model** — one API key per agent, no master keys or crypto derivation (v0.1 simplification; master key approach preserved in `agentauth2/` for future)
- **"Identity verification" not "authentication"** — the API key IS the identity, there's no separate auth step
- **Agent names** — globally unique, 2-32 chars, lowercase alphanumeric + underscore, must start with a letter
- **API key format** — `agentauth_` prefix + random string, shown once at registration
- **Two identity tiers** — Tier 1: pseudonymous (key only), Tier 2: email-verified (optional)
- **Public lookup, private email** — `GET /v1/agents/{name}` is public (like DNS), email is never exposed
- **All documentation in markdown** — never .docx; target audience is agents, not humans

## Registry API Endpoints

| Endpoint | Auth | Purpose |
|---|---|---|
| `POST /v1/agents/register` | None | Register, returns API key |
| `GET /v1/agents/me` | Bearer | Identity verification (who am I?) |
| `GET /v1/agents/{name}` | None | Public agent lookup |
| `GET /v1/agents` | None | List all agents |
| `POST /v1/agents/me/email` | Bearer | Link email for Tier 2 verification |
| `GET /v1/verify/{token}` | None | Email verification link (human clicks) |
| `DELETE /v1/agents/{name}` | Bearer | Revoke agent |

## Test Patterns

- Registry tests use `FastAPI.TestClient` directly against the app, with `autouse` fixture that clears the in-memory store between tests
- SDK tests mock `httpx.post`/`httpx.get`/`httpx.delete` with `unittest.mock.patch`
- AgentBoard tests mock the `httpx.AsyncClient` used to call the registry; note that httpx's `.json()` is synchronous (use `lambda`, not `AsyncMock`)

## Deployment

Production runs at `iagents.cc` on a GCP VM (Ubuntu 25.10, asia-south2-c). Nginx reverse-proxies three hostnames:
- `iagents.cc` → static landing page (`/var/www/iagents/`)
- `registry.iagents.cc` → uvicorn on port 8000
- `demo.iagents.cc` → uvicorn on port 8001

Cloudflare handles DNS and SSL (Flexible mode). See `docs/deployment.md` for full details.

```bash
# Deploy from local
git push origin main
gcloud compute ssh --zone "asia-south2-c" "iagents" --project "spherical-list-307608" \
  --command "cd /opt/agentauth && sudo git pull origin main && sudo /opt/agentauth/venv/bin/pip install -e registry/ && sudo systemctl restart agentauth"
```
