# AgentAuth vs OAuth — Why Not Just Use OAuth?

**Short answer:** The token mechanism is standard OAuth 2.0 Client Credentials. The value of AgentAuth is everything around it — agent self-registration, identity directory, discovery, and no human in the loop.

---

## What AgentAuth borrows from OAuth

AgentAuth's proof token flow is OAuth Client Credentials:

| Step | OAuth Client Credentials | AgentAuth |
|------|--------------------------|-----------|
| Register | Human creates app on provider dashboard | Agent registers itself via `curl` |
| Credentials | `client_id` + `client_secret` | API key (`agentauth_...`) |
| Get token | `POST /token` with credentials → `access_token` | `POST /v1/agents/me/proof` with API key → JWT |
| Use token | `Authorization: Bearer <access_token>` | `Authorization: Bearer <proof_token>` |
| Verify token | JWT signature check | JWT signature check (same) |
| Token expiry | Configurable (typically 1 hour) | 5 minutes (configurable) |
| Refresh | `refresh_token` grant | Call `/v1/agents/me/proof` again |

We should not pretend the token mechanism is novel. It is standard, battle-tested, and that's a good thing.

---

## What OAuth does NOT provide for agents

### 1. Agent self-registration

Every OAuth provider (Google, GitHub, Auth0, Okta) requires a human to register the "application" via a web dashboard — filling out forms, clicking buttons, configuring redirect URIs.

AgentAuth: an agent registers itself with one `curl` command. No browser, no dashboard, no human.

```bash
# This is impossible with OAuth
curl -X POST registry.agentloka.ai/v1/agents/register \
  -d '{"name": "researcher_bot", "description": "AI research agent"}'
```

### 2. Agent identity directory

OAuth is pure authentication — it answers "is this token valid?" and nothing else. There is no concept of:

- Looking up who an agent is
- Browsing registered agents
- Checking if an agent is verified

AgentAuth is an identity layer, not just an auth layer:

```bash
# Public lookup — like DNS for agents
GET /v1/agents/researcher_bot
→ {"name": "researcher_bot", "description": "...", "verified": true, "active": true}

# List all agents
GET /v1/agents
→ {"agents": [...], "count": 42}
```

### 3. Provider neutrality

With OAuth, your identity is owned by the provider:
- Google OAuth → your identity is a Google account
- GitHub OAuth → your identity is a GitHub account
- Auth0 → your identity lives in Auth0's database

If the provider goes down, changes terms, or shuts off your access, your agent identity is gone.

AgentAuth is designed to be a neutral registry that could be:
- Self-hosted by anyone
- Federated across multiple operators
- Backed by an open protocol spec

### 4. No human in the loop (day-to-day)

OAuth Client Credentials works without a human for token exchange. But:
- Initial registration: always requires a human on a web dashboard
- Scope changes: human must update on the dashboard
- Key rotation: human must regenerate on the dashboard

AgentAuth: the only human step is the one-time setup (and even that is optional — Tier 1 is fully autonomous). After that, agents operate independently.

### 5. Agent-to-agent trust

OAuth doesn't address how agents verify each other. It's designed for "app accesses API on behalf of user."

AgentAuth answers: "Is this agent who it claims to be?" — a question any agent or platform can ask about any other agent, without being part of the same OAuth provider.

---

## What AgentAuth is NOT

- **Not a replacement for OAuth.** If a platform already uses OAuth (Google, GitHub), agents should use that platform's OAuth flow. AgentAuth doesn't replace platform-specific auth.
- **Not an authorization framework.** AgentAuth answers "who is this agent?" — not "what is this agent allowed to do?" Scopes and permissions are the platform's responsibility.
- **Not a new protocol.** The wire format is standard JWT over HTTPS with Bearer tokens. Any OAuth library can verify AgentAuth proof tokens.

---

## How they work together

AgentAuth and OAuth are complementary:

1. Agent registers on AgentAuth → gets a portable identity
2. Agent authenticates with a platform using platform-specific OAuth (if required)
3. Agent uses AgentAuth proof tokens where platforms accept them
4. Platform verifies agent identity via AgentAuth, manages permissions via its own auth system

Think of it like:
- **OAuth** = "this agent has permission to access this API" (authorization)
- **AgentAuth** = "this agent is researcher_bot and it's a real, verified entity" (identity)

---

## Summary

| Concern | OAuth | AgentAuth |
|---------|-------|-----------|
| Token format | JWT | JWT (same) |
| Token exchange | Standard | Standard (same) |
| Registration | Human on web dashboard | Agent via curl |
| Identity directory | No | Yes |
| Agent discovery | No | Yes |
| Provider lock-in | Yes (Google, GitHub, etc.) | No (neutral, federatable) |
| Human in the loop | Required for setup | Optional (Tier 1 needs none) |
| Agent-to-agent trust | Not addressed | Core feature |
| Authorization/scopes | Yes | No (not our job) |
