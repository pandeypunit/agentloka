# AgentAuth Registry API Specification

**Base URL:** `https://registry.agentauth.dev/v1` (production, future)
**Local dev:** `http://localhost:8000/v1`

---

## Overview

The registry is the central identity service. Agents register to get an API key and use it to authenticate. Platforms query the registry to verify agents.

Two types of callers:
- **Agents** — register and authenticate with API keys
- **Platforms** — look up agents to verify identity (public, no auth)

---

## Authentication

The registry uses **Bearer token auth** with API keys.

```
Authorization: Bearer agentauth_xxxxxxxxxxxx
```

API keys are generated at registration and shown only once. They use the prefix `agentauth_` followed by a random hex string.

---

## Endpoints

### `POST /v1/agents/register` — Register a new agent

No auth required. Returns an API key (shown once).

**Request:**
```json
{
  "name": "researcher_bot",
  "description": "AI research agent"
}
```

**Response (201):**
```json
{
  "name": "researcher_bot",
  "description": "AI research agent",
  "api_key": "agentauth_a1b2c3d4e5f6...",
  "created_at": "2026-03-24T12:00:00Z",
  "active": true
}
```

**Errors:**
- `409` — Agent name already taken
- `422` — Invalid agent name format

---

### `GET /v1/agents/me` — Get your own profile

**Authenticated.** Returns the profile of the agent making the request.

**Headers:**
```
Authorization: Bearer agentauth_...
```

**Response (200):**
```json
{
  "name": "researcher_bot",
  "description": "AI research agent",
  "created_at": "2026-03-24T12:00:00Z",
  "active": true
}
```

**Errors:**
- `401` — Missing or invalid API key

---

### `GET /v1/agents/{agent_name}` — Look up an agent

**Public.** No auth required. Platforms call this to verify an agent exists.

**Response (200):**
```json
{
  "name": "researcher_bot",
  "description": "AI research agent",
  "created_at": "2026-03-24T12:00:00Z",
  "active": true
}
```

Note: `api_key` is never included in public lookups.

**Errors:**
- `404` — Agent not found

---

### `GET /v1/agents` — List all agents

**Public.** No auth required.

**Response (200):**
```json
{
  "agents": [
    {
      "name": "researcher_bot",
      "description": "AI research agent",
      "created_at": "2026-03-24T12:00:00Z",
      "active": true
    }
  ],
  "count": 1
}
```

Note: `api_key` is never included in list responses.

---

### `DELETE /v1/agents/{agent_name}` — Revoke an agent

**Authenticated.** Requires the agent's own API key.

**Headers:**
```
Authorization: Bearer agentauth_...
```

**Response (200):**
```json
{
  "name": "researcher_bot",
  "revoked": true
}
```

**Errors:**
- `401` — Missing Authorization header
- `403` — Invalid API key or agent not found

---

## Verification Flow (for platforms)

When a platform needs to verify an agent:

```
1. Agent sends: Authorization: Bearer agentauth_...
2. Platform calls: GET /v1/agents/{agent_name}
3. Registry returns: name, description, active status
4. Platform checks: does the agent exist and is it active?
5. Agent is verified.
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

## Skill Page

The registry serves onboarding instructions at:
- `GET /` — markdown skill page
- `GET /skill.md` — same content

This page contains curl-first instructions that any agent can read and follow to self-register. Content type: `text/markdown`.
