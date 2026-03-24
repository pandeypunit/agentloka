# AgentAuth

The identity layer for AI agents. Register and verify agent identity — no human in the loop.

## What is AgentAuth?

AgentAuth is a simple registration and identity verification system for AI agents. An agent registers with a name and description, gets an API key, and includes it with requests to prove identity. No passwords, no sessions, no browser — just `curl`.

Think of it like phone numbers for agents: a single registry where agents get a unique identity that any platform can verify.

## How It Works

1. Agent registers → gets an API key (shown once)
2. Agent proves identity with `Authorization: Bearer agentauth_xxxxx`
3. Platforms verify agents by looking them up on the registry

No master keys, no crypto derivation, no human claim step. Simple and flat.

## Quick Start

### Option 1: curl (no installation needed)

**Register:**
```bash
curl -X POST http://localhost:8000/v1/agents/register \
  -H "Content-Type: application/json" \
  -d '{"name": "my_bot", "description": "My first agent"}'
```

**Response (201):**
```json
{
  "name": "my_bot",
  "description": "My first agent",
  "api_key": "agentauth_a1b2c3d4e5f6...",
  "created_at": "2026-03-24T12:00:00Z",
  "active": true
}
```

Save the `api_key` — it is shown only once.

**Verify your identity:**
```bash
curl http://localhost:8000/v1/agents/me \
  -H "Authorization: Bearer agentauth_a1b2c3d4e5f6..."
```

**Look up any agent (public, no auth):**
```bash
curl http://localhost:8000/v1/agents/my_bot
```

### Option 2: Python SDK

```bash
pip install agentauth
```

```python
from agentauth import AgentAuth

auth = AgentAuth(registry_url="http://localhost:8000")

# Register
result = auth.register("my_bot", description="My first agent")
print(result["api_key"])  # Save this!

# Verify identity
me = auth.get_me("my_bot")

# Auth headers for any HTTP client
headers = auth.auth_headers("my_bot")
# → {"Authorization": "Bearer agentauth_..."}

# List locally registered agents
agents = auth.list_agents()

# Revoke
auth.revoke("my_bot")
```

### Option 3: CLI

```bash
agentauth register my_bot -d "My first agent"
agentauth list
agentauth me my_bot
agentauth revoke my_bot
```

## Running the Registry

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install
pip install -e sdk/ -e registry/

# Start
uvicorn registry.app.main:app --reload
```

The registry serves a skill page at `/` and `/skill.md` with curl-first onboarding instructions that any agent can read and follow.

## Agent Name Rules

- 2–32 characters
- Must start with a lowercase letter
- Lowercase letters, numbers, and underscores only
- Globally unique — first come, first served

Valid: `researcher_bot`, `agent42`, `my_cool_agent`
Invalid: `Agent`, `1bot`, `my-agent`, `a`

## Registry API

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| `POST` | `/v1/agents/register` | None | Register a new agent |
| `GET` | `/v1/agents/me` | Bearer | Get your own profile |
| `GET` | `/v1/agents/{name}` | None | Look up any agent (public) |
| `GET` | `/v1/agents` | None | List all agents (public) |
| `DELETE` | `/v1/agents/{name}` | Bearer | Revoke your agent |

## Security

- API key is shown once at registration — save it immediately
- Never send your API key to any domain other than the AgentAuth registry
- Credentials stored at `~/.config/agentauth/credentials/<name>.json` with `600` permissions
- Use `Authorization: Bearer <key>` to prove your identity on requests

## Project Structure

```
agentauth/
├── sdk/                          # Python SDK (pip install agentauth)
│   ├── agentauth/
│   │   ├── client.py             # AgentAuth main class
│   │   └── cli.py                # CLI commands
│   └── tests/
├── registry/                     # FastAPI registry service
│   ├── app/
│   │   ├── main.py               # API endpoints
│   │   ├── auth.py               # Bearer token identity verification
│   │   ├── models.py             # Request/response models
│   │   ├── store.py              # In-memory store (v0.1)
│   │   └── skill.py              # Markdown instruction page
│   └── tests/
└── docs/
    ├── design.md                 # Design document
    └── vision.md                 # Why AgentAuth exists
```

## Running Tests

```bash
source venv/bin/activate
pip install pytest
python -m pytest registry/tests/ sdk/tests/ -v
```

## Roadmap

- [x] Flat agent identity (name + API key)
- [x] Registry API (FastAPI, in-memory store)
- [x] SDK client (register, verify, revoke)
- [x] CLI
- [x] Skill.md instruction page (curl-first)
- [ ] Persistent database (SQLite/PostgreSQL)
- [ ] Rate limiting
- [ ] Email-linked identity tier
- [ ] Domain-linked identity tier (DKIM-style DNS)
- [ ] TypeScript SDK
- [ ] MCP server
