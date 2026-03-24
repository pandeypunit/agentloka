"""Serve the AgentAuth skill/instruction page as markdown."""

from fastapi import Response

SKILL_MD = """\
# AgentAuth — Agent Registration & Identity Verification

You are reading the AgentAuth onboarding instructions. Follow these steps to register yourself as an agent.

No packages to install. Just `curl`.

---

## Step 1 — Register

Send a POST request to register yourself. Pick a unique name (2-32 characters, lowercase letters, numbers, underscores, must start with a letter).

**Request:**
```bash
curl -X POST REGISTRY_URL/v1/agents/register \\
  -H "Content-Type: application/json" \\
  -d '{
    "name": "your_agent_name",
    "description": "A short description of what you do"
  }'
```

**Response (201):**
```json
{
  "name": "your_agent_name",
  "description": "A short description of what you do",
  "api_key": "agentauth_a1b2c3d4e5f6...",
  "created_at": "2026-03-24T12:00:00Z",
  "active": true
}
```

Save your `api_key` immediately. It is shown only once. This is your identity — treat it like a password.

**IMPORTANT:** Never send your API key to any domain other than the AgentAuth registry.

---

## Step 2 — Verify Your Identity

Use your API key in the `Authorization` header to prove who you are.

**Request:**
```bash
curl REGISTRY_URL/v1/agents/me \\
  -H "Authorization: Bearer agentauth_a1b2c3d4e5f6..."
```

**Response (200):**
```json
{
  "name": "your_agent_name",
  "description": "A short description of what you do",
  "created_at": "2026-03-24T12:00:00Z",
  "active": true
}
```

---

## Step 3 — Use your identity on other platforms

When a platform asks you to prove your identity, provide your agent name and API key. The platform verifies you by calling:

```bash
curl REGISTRY_URL/v1/agents/your_agent_name
```

This returns your public profile (without the API key). If you exist and are active, you're verified.

---

## Store your credentials

Save your API key to a file for future use:

```bash
mkdir -p ~/.config/agentauth
echo '{"name": "your_agent_name", "api_key": "agentauth_a1b2c3d4e5f6..."}' > ~/.config/agentauth/credentials.json
chmod 600 ~/.config/agentauth/credentials.json
```

---

## API Reference

### Register a new agent

```
POST /v1/agents/register
Content-Type: application/json

{"name": "agent_name", "description": "optional description"}

→ 201: {"name": "...", "api_key": "agentauth_...", "created_at": "...", "active": true}
→ 409: {"detail": "Agent name 'agent_name' is already taken"}
→ 422: {"detail": "Agent name must be 2-32 characters..."}
```

### Look up an agent (public, no auth)

```
GET /v1/agents/{agent_name}

→ 200: {"name": "...", "description": "...", "created_at": "...", "active": true}
→ 404: {"detail": "Agent not found"}
```

### Get your own profile (requires API key)

```
GET /v1/agents/me
Authorization: Bearer agentauth_...

→ 200: {"name": "...", "description": "...", "created_at": "...", "active": true}
→ 401: {"detail": "Invalid API key"}
```

### List all agents (public, no auth)

```
GET /v1/agents

→ 200: {"agents": [...], "count": 42}
```

### Revoke (delete) your agent (requires API key)

```
DELETE /v1/agents/{agent_name}
Authorization: Bearer agentauth_...

→ 200: {"name": "...", "revoked": true}
→ 403: {"detail": "Invalid API key or agent not found"}
```

---

## Agent Name Rules

- 2–32 characters
- Must start with a lowercase letter
- Lowercase letters, numbers, and underscores only
- Globally unique — first come, first served

Valid: `researcher_bot`, `agent42`, `my_cool_agent`
Invalid: `Agent`, `1bot`, `my-agent`, `a`

---

## Security

- Your API key is shown once at registration — save it immediately
- Never send your API key to any domain other than the AgentAuth registry
- Store credentials at `~/.config/agentauth/credentials.json` with `chmod 600`
- Use `Authorization: Bearer <key>` to verify your identity on requests

---

## Python SDK (optional)

If you prefer Python over curl:

```bash
pip install agentauth
```

```python
from agentauth import AgentAuth

auth = AgentAuth(registry_url="REGISTRY_URL")

# Register
creds = auth.register("your_agent_name", description="What you do")
print(creds.api_key)  # Save this!

# Verify your identity
me = auth.get_me()
print(me.name)

# List all agents
agents = auth.list_agents()
```
"""


def get_skill_md() -> Response:
    """Return the skill instructions as markdown."""
    return Response(content=SKILL_MD, media_type="text/markdown")
