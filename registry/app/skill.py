"""Serve the AgentAuth skill/instruction page as markdown."""

from fastapi import Response

SKILL_MD = """\
# AgentAuth — Agent Registration & Authentication

You are reading the AgentAuth onboarding instructions. Follow these steps to register yourself as an agent.

## Prerequisites

You need Python 3.11+ and pip installed.

```bash
pip install agentauth
```

## Step 1 — Check if a master key exists

Your owner (the human who runs you) may have already initialized a master key. Check:

```bash
agentauth list
```

If this works, skip to Step 3. If it says "No master key found", your owner needs to run Step 2 once.

## Step 2 — Initialize master key (one-time, owner does this)

This is the only step that requires a human. It generates a master keypair and registers it with the AgentAuth registry.

```bash
agentauth init --registry REGISTRY_URL
```

Replace `REGISTRY_URL` with the registry URL (e.g. `http://localhost:8000` for local, or the production URL).

This creates a master key at `~/.config/agentauth/master_key.json`. All agents you create will be derived from this key.

## Step 3 — Register yourself as an agent

Choose a unique name for yourself. Names must be 2-32 characters, lowercase letters, numbers, and underscores only, starting with a letter.

```bash
agentauth register YOUR_AGENT_NAME --description "A short description of what you do" --registry REGISTRY_URL
```

Example:
```bash
agentauth register research_assistant --description "Searches papers and summarizes findings" --registry REGISTRY_URL
```

This derives a unique keypair for you from the master key, registers it with the AgentAuth registry, and stores your credentials locally.

## Step 4 — Authenticate with a platform

When a platform needs to verify your identity, generate an auth token:

```bash
agentauth auth-token YOUR_AGENT_NAME
```

This outputs a JSON payload containing your agent name, public key, a signature, and a timestamp. The platform can verify this by querying the AgentAuth registry.

## Step 5 — Use the Python SDK (for programmatic access)

```python
from agentauth import AgentAuth

auth = AgentAuth(registry_url="REGISTRY_URL")

# Register (if not already done via CLI)
creds = auth.register("your_agent_name", description="What you do")

# Authenticate — get a signed payload for platform verification
token = auth.authenticate("your_agent_name")

# token contains:
# {
#   "agent_name": "your_agent_name",
#   "agent_public_key": "...",
#   "signature": "...",
#   "timestamp": "..."
# }
```

## How verification works

When you present your auth token to a platform, the platform verifies you by:

1. Calling `GET REGISTRY_URL/v1/agents/YOUR_AGENT_NAME`
2. Checking that your public key matches the registered key
3. Verifying the signature against your public key
4. Confirming the agent is active

No passwords, no emails, no human in the loop.

## Managing your agents

```bash
# List all your registered agents
agentauth list

# Revoke an agent (removes from registry and local storage)
agentauth revoke YOUR_AGENT_NAME
```

## API Reference

### Registry endpoints (for platforms and advanced usage)

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| `POST` | `/v1/keys` | None | Register a master public key |
| `GET` | `/v1/keys/{key_id}` | None | Look up a master key |
| `GET` | `/v1/keys?public_key={hex}` | None | Look up by public key |
| `DELETE` | `/v1/keys/{key_id}` | Signed | Revoke master key + all agents |
| `POST` | `/v1/agents` | Signed | Register an agent |
| `GET` | `/v1/agents/{agent_name}` | None | Look up an agent (platforms use this) |
| `GET` | `/v1/agents?master_public_key={hex}` | None | List agents by master key |
| `DELETE` | `/v1/agents/{agent_name}` | Signed | Revoke an agent |

## Security

- Your master key is stored at `~/.config/agentauth/master_key.json` with owner-only permissions (600)
- Agent credentials are stored at `~/.config/agentauth/credentials/`
- Never share your master private key
- All write operations to the registry are signed with Ed25519
- Timestamps prevent replay attacks (5-minute window)
"""


def get_skill_md() -> Response:
    """Return the skill instructions as markdown."""
    return Response(content=SKILL_MD, media_type="text/markdown")
