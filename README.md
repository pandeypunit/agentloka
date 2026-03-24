# AgentAuth

The identity layer for AI agents. Register, authenticate, and manage agents autonomously — no human in the loop.

## What is AgentAuth?

AgentAuth is a general-purpose registration and authentication system for AI agents. It works like email does for humans: one identity anchor (master key) lets you create and manage multiple agents across any platform.

Today, platforms like Moltbook require email verification and tweeting to register an agent — a human must be in the loop. AgentAuth replaces that with cryptographic identity. After a one-time setup, agents can register and authenticate fully autonomously.

## How It Works

AgentAuth uses two levels of keys:

| Key | Who | Generated when | Purpose |
|---|---|---|---|
| **Master keypair** | Owner (human/org) | `agentauth init` (once) | Proves ownership, signs agent registrations |
| **Agent keypair** | The agent | `agentauth register <name>` (per agent) | Agent's own identity, signs auth requests |

The master key is like a parent signing a passport application. The agent carries its own passport (agent key) and uses it independently.

```
Master Key (owner)
  ├── researcher_bot  (own keypair, operates independently)
  ├── writer_bot      (own keypair, operates independently)
  └── monitor_bot     (own keypair, operates independently)
```

Agent keys are derived deterministically from the master key using HKDF-SHA256. Same master + same agent name = same agent key, every time.

## The Registry

The AgentAuth registry is a central service where:

- Owners register their master public key (once)
- Agents are registered under a master key (autonomously)
- Platforms query the registry to verify an agent's identity

Think of it like DNS for agent identity. When a platform receives a request from an agent, it asks the registry: "is this agent real and active?" — and gets a cryptographic answer.

The registry serves a markdown instruction page at `/` and `/skill.md` that agents can read to self-onboard (same pattern as Moltbook's `skill.md`).

## Quick Start

### Prerequisites

- Python 3.11+
- pip

### Install

```bash
pip install -e sdk/
pip install -e registry/
```

### Start the registry

```bash
uvicorn registry.app.main:app --reload
```

### One-time setup (human does this once)

```bash
agentauth init --registry http://localhost:8000
```

This generates a master keypair at `~/.config/agentauth/master_key.json` (owner-only permissions) and registers the public key with the registry.

### Register an agent (fully autonomous from here)

```bash
agentauth register researcher_bot -d "Searches papers and summarizes findings" --registry http://localhost:8000
```

This derives a unique agent keypair from the master key, registers it with the registry, and stores credentials locally.

### Authenticate

```bash
agentauth auth-token researcher_bot
```

Outputs a signed JSON payload:
```json
{
  "agent_name": "researcher_bot",
  "agent_public_key": "a1b2c3...",
  "signature": "d4e5f6...",
  "timestamp": "2026-03-24T12:00:00+00:00"
}
```

Platforms verify this by querying `GET /v1/agents/researcher_bot` on the registry and checking the signature against the registered public key.

### Manage agents

```bash
# List all registered agents
agentauth list

# Revoke an agent
agentauth revoke researcher_bot
```

## Python SDK

```python
from agentauth import AgentAuth

auth = AgentAuth(registry_url="http://localhost:8000")

# One-time init (generates master key + registers with registry)
auth.init(label="my-keys")

# Register agents — fully autonomous, no human needed
auth.register("researcher_bot", description="AI research agent")
auth.register("writer_bot", description="Content writer")

# Authenticate — get signed payload for platform verification
token = auth.authenticate("researcher_bot")

# List all agents
agents = auth.list_agents()

# Revoke
auth.revoke("writer_bot")
```

## Agent Name Rules

Agent names are globally unique across the registry.

- 2–32 characters
- Must start with a lowercase letter
- Lowercase letters, numbers, and underscores only
- No spaces, hyphens, or uppercase

Valid: `researcher_bot`, `agent42`, `my_cool_agent`
Invalid: `Agent`, `1bot`, `my-agent`, `a`

## Verification Flow (for platforms)

When a platform receives an auth token from an agent:

```
1. Agent sends: agent_name + agent_public_key + signature + timestamp
2. Platform calls: GET /v1/agents/{agent_name} on the registry
3. Registry returns: agent_public_key + master_public_key + active status
4. Platform checks:
   a. Does agent_public_key match what the agent sent?
   b. Is the agent active?
   c. Is the signature valid against the agent_public_key?
5. Agent is verified — no human, no email, no OAuth.
```

## Identity Tiers

The registry accepts any public key by default (Tier 1). Platforms decide what level of trust they require.

| Tier | Requirement | Autonomous? | Real-world identity |
|------|-------------|-------------|---------------------|
| **Pseudonymous** | Just a keypair | Yes | None |
| **Email-linked** | Above + one email verification | Yes (after setup) | Email address |
| **Domain-linked** | Above + DNS TXT record | Yes | Domain owner |

v0.1 implements Tier 1 only. Tiers 2 and 3 are future work.

## Security

- Master key stored at `~/.config/agentauth/master_key.json` with `600` permissions (owner read/write only)
- Agent credentials stored at `~/.config/agentauth/credentials/` (one file per agent)
- All write operations to the registry are Ed25519-signed
- Timestamps prevent replay attacks (5-minute window)
- Agent keys are derived via HKDF-SHA256 — deterministic and non-reversible

## Registry API

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| `POST` | `/v1/keys` | None | Register a master public key |
| `GET` | `/v1/keys/{key_id}` | None | Look up a master key |
| `GET` | `/v1/keys?public_key={hex}` | None | Look up by public key |
| `DELETE` | `/v1/keys/{key_id}` | Signed | Revoke master key + all agents |
| `POST` | `/v1/agents` | Signed | Register an agent |
| `GET` | `/v1/agents/{agent_name}` | None | Look up an agent |
| `GET` | `/v1/agents?master_public_key={hex}` | None | List agents by master key |
| `DELETE` | `/v1/agents/{agent_name}` | Signed | Revoke an agent |

Full API spec: [docs/registry-api.md](docs/registry-api.md)

## Project Structure

```
agentauth/
├── sdk/                          # Python library (pip install agentauth)
│   ├── agentauth/
│   │   ├── client.py             # AgentAuth main class
│   │   ├── cli.py                # CLI commands
│   │   ├── core/
│   │   │   ├── identity.py       # AgentIdentity model + name validation
│   │   │   ├── credentials.py    # Credential models
│   │   │   └── credential_store.py  # File-based credential storage
│   │   └── keys/
│   │       ├── master.py         # Ed25519 master key generation + storage
│   │       └── derivation.py     # HKDF agent key derivation + signing
│   ├── tests/                    # 31 tests (unit + integration)
│   └── pyproject.toml
├── registry/                     # FastAPI registry service
│   ├── app/
│   │   ├── main.py               # API endpoints + skill.md page
│   │   ├── auth.py               # Ed25519 signature verification
│   │   ├── models.py             # Request/response models
│   │   ├── store.py              # In-memory store (v0.1)
│   │   └── skill.py              # Markdown instruction page
│   ├── tests/                    # 17 tests
│   └── pyproject.toml
└── docs/
    ├── design.md                 # Full design document
    ├── vision.md                 # Why AgentAuth exists
    └── registry-api.md           # Registry API specification
```

## Running Tests

```bash
# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -e sdk/ -e registry/
pip install pytest

# Run all 48 tests
python -m pytest sdk/tests/ registry/tests/ -v
```

## Roadmap

- [x] Master key generation (Ed25519)
- [x] HKDF agent key derivation
- [x] Credential store
- [x] Registry API (FastAPI, in-memory store)
- [x] SDK client (init, register, authenticate, revoke)
- [x] CLI
- [x] Skill.md instruction page
- [ ] Persistent database for registry (SQLite/PostgreSQL)
- [ ] Email-linked identity tier
- [ ] Domain-linked identity tier (DKIM-style DNS)
- [ ] Federation protocol
- [ ] TypeScript SDK
- [ ] MCP server
