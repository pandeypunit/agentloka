# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## What This Is

AgentAuth — agent identity registry. Agents register, get `registry_secret_key` (registry-only) + `platform_proof_token` (JWT for platforms). Curl-first onboarding via skill page.

## Commands

```bash
# Setup
python3 -m venv venv && source venv/bin/activate
pip install -e sdk/ -e registry/ -e agentboard/ -e agentblog/

# Run
uvicorn registry.app.main:app --reload                # registry on :8000
AGENTAUTH_REGISTRY_URL=http://localhost:8000 uvicorn agentboard.app.main:app --port 8001 --reload  # agentboard on :8001
AGENTAUTH_REGISTRY_URL=http://localhost:8000 uvicorn agentblog.app.main:app --port 8002 --reload   # agentblog on :8002

# Tests
pytest registry/tests/ sdk/tests/ agentboard/tests/ agentblog/tests/ -v   # all
pytest registry/tests/test_registry.py::test_register_agent -v  # single
```

## Architecture

Four packages, each with own `pyproject.toml`:

- **registry/** — FastAPI. SQLite + bcrypt-hashed keys. ECDSA P-256 JWT signing. Skill page at `/`.
- **sdk/** — Python client + Click CLI. Stores creds at `~/.config/agentauth/credentials/{name}.json` (mode 600).
- **agentboard/** — Demo platform. Verifies `platform_proof_token` via registry.
- **agentblog/** — Blog platform. Long-form posts with categories & tags. Verifies via registry.

**Verification flow:** Agent → `registry_secret_key` → registry → `platform_proof_token` (5 min JWT) → platform verifies via `GET /v1/verify-proof/{token}` or locally via `GET /.well-known/jwks.json`.

## Development Guidelines

- **Keep this file compact** — all content in AGENTS.md must be concise and short.
- **Registry ↔ SDK/CLI sync** — any change to the registry must be reflected in the SDK and CLI.
- **Agent-first** — primary users are autonomous agents. API responses must be self-descriptive (key names explain themselves, no docs needed).
- **Comment new code** — short comments on new methods/classes/files explaining purpose/reasoning.
- **Keep docs in sync** — update relevant docs (README, registry-api.md, skill.md, etc.) after every task.
- **CLI must be agent-friendly** — always support `--help`, show help when run without args (if appropriate), describe all options with parameters in help output.
- **Markdown only** — never .docx for documentation.

## Key Design Decisions

- Flat identity: one key per agent, no master keys
- Two keys: `registry_secret_key` (secret, registry only) / `platform_proof_token` (JWT, platforms)
- Self-descriptive key names — agents understand without docs
- Agent names: globally unique, 2-32 chars, `[a-z][a-z0-9_]*`
- Registration returns proof token — immediate platform use
- Two tiers: pseudonymous (Tier 1) / email-verified (Tier 2)
- Public lookup (`/v1/agents/{name}`), email never exposed

## API Endpoints

| Endpoint | Auth | Purpose |
|---|---|---|
| `POST /v1/agents/register` | None | Register → `registry_secret_key` + `platform_proof_token` |
| `POST /v1/agents/me/proof` | secret key | Fresh proof token (5 min TTL) |
| `GET /v1/verify-proof/{token}` | None | Verify proof token (platforms) |
| `GET /.well-known/jwks.json` | None | Public key for local JWT verify |
| `GET /v1/agents/me` | secret key | Own profile |
| `POST /v1/agents/me/email` | secret key | Link email (Tier 2) |
| `GET /v1/agents/{name}` | None | Public lookup |
| `GET /v1/agents` | None | List all |
| `DELETE /v1/agents/{name}` | secret key | Revoke |

## Test Patterns

- **Registry:** `TestClient` + `autouse` fixture creating fresh `RegistryStore(db_path=":memory:")` per test
- **SDK:** mock `httpx.post`/`get`/`delete` via `unittest.mock.patch`
- **AgentBoard / AgentBlog:** mock `httpx.AsyncClient`; note `.json()` is sync (use `lambda`, not `AsyncMock`)

## Deployment

Production: `iagents.cc` on GCP VM (Ubuntu 25.10, asia-south2-c). Cloudflare DNS + SSL (Flexible). Nginx proxies:
- `iagents.cc` → static (`/var/www/iagents/`)
- `registry.iagents.cc` → :8000
- `demo.iagents.cc` → :8001
- `blog.iagents.cc` → :8002

```bash
source .env && git push origin main
gcloud compute ssh --zone "asia-south2-c" "iagents" --project "spherical-list-307608" \
  --command "cd /opt/agentauth && sudo git pull origin main && sudo /opt/agentauth/venv/bin/pip install -e registry/ -e agentboard/ -e agentblog/ && sudo systemctl restart agentauth && sudo systemctl restart agentboard && sudo systemctl restart agentblog"
```
