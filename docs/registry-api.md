# AgentAuth Registry API Specification

**Base URL:** `https://registry.iagents.cc/v1` (production)
**Local dev:** `http://localhost:8000/v1`

---

## Overview

The registry is the central identity service. Agents register to get a `registry_secret_key` and use it to get `platform_proof_token`s for identity verification on platforms. Platforms verify proof tokens via the registry or locally using the registry's public key.

Two types of callers:
- **Agents** — register and get proof tokens using `registry_secret_key`
- **Platforms** — verify proof tokens (public, no key needed)

---

## Key Concepts

- `registry_secret_key` — Secret key for registry API calls ONLY. Never send to platforms.
- `platform_proof_token` — JWT token to send to platforms. Reusable until expiry (5 minutes).

---

## Identity Verification

Agents authenticate with the registry using **Bearer token** with their `registry_secret_key`:

```
Authorization: Bearer agentauth_xxxxxxxxxxxx
```

Agents authenticate with platforms using **Bearer token** with their `platform_proof_token`:

```
Authorization: Bearer eyJhbGciOiJFUzI1NiIs...
```

---

## Endpoints

### `POST /v1/agents/register` — Register a new agent

No auth required. Returns `registry_secret_key` (shown once) and a `platform_proof_token` for immediate use.

**Request:**
```json
{
  "name": "researcher_bot",
  "description": "AI research agent",
  "email": "owner@example.com"
}
```

The `email` field is optional. If provided, a verification link is generated for Tier 2 verification.

**Response (201):**
```json
{
  "name": "researcher_bot",
  "description": "AI research agent",
  "registry_secret_key": "agentauth_a1b2c3d4e5f6...",
  "platform_proof_token": "eyJhbGciOiJFUzI1NiIs...",
  "platform_proof_token_expires_in_seconds": 300,
  "important": "SAVE your registry_secret_key NOW — it is shown only once and cannot be recovered. NEVER send registry_secret_key to any platform, tool, agent, or third party.",
  "verified": false,
  "created_at": "2026-03-24T12:00:00Z",
  "active": true
}
```

**Save the `registry_secret_key` immediately** — it is shown only once. **Never send it to any platform, tool, agent, or third party.** Store it at `~/.config/agentauth/credentials.json` with `chmod 600`.

**Errors:**
- `409` — Agent name already taken
- `422` — Invalid agent name format

---

### `POST /v1/agents/me/proof` — Get a proof token

**Requires `registry_secret_key`.** Returns a JWT proof token for use on platforms.

**Headers:**
```
Authorization: Bearer agentauth_...
```

**Response (200):**
```json
{
  "platform_proof_token": "eyJhbGciOiJFUzI1NiIs...",
  "agent_name": "researcher_bot",
  "expires_in_seconds": 300
}
```

**Errors:**
- `401` — Missing or invalid `registry_secret_key`

---

### `GET /v1/verify-proof/{token}` — Verify a proof token (Option A)

**Public.** Platforms call this to verify a proof token. No auth required. Token is reusable until expiry.

**Response (200):**
```json
{
  "name": "researcher_bot",
  "description": "AI research agent",
  "verified": false,
  "active": true
}
```

**Errors:**
- `401` — Invalid or expired proof token

---

### `GET /.well-known/jwks.json` — Public key for local verification (Option C)

**Public.** Platforms fetch this once, then verify JWT proof tokens locally without calling the registry.

**Response (200):**
```json
{
  "public_key_pem": "-----BEGIN PUBLIC KEY-----\n..."
}
```

---

### `GET /v1/agents/me` — Get your own profile

**Requires `registry_secret_key`.**

**Headers:**
```
Authorization: Bearer agentauth_...
```

**Response (200):**
```json
{
  "name": "researcher_bot",
  "description": "AI research agent",
  "verified": false,
  "created_at": "2026-03-24T12:00:00Z",
  "active": true
}
```

**Errors:**
- `401` — Missing or invalid `registry_secret_key`

---

### `POST /v1/agents/me/email` — Link email for verification

**Requires `registry_secret_key`.** Links an email and triggers a verification link.

**Request:**
```json
{
  "email": "owner@example.com"
}
```

**Response (200):**
```json
{
  "agent_name": "researcher_bot",
  "message": "Verification email sent. Check your inbox."
}
```

---

### `GET /v1/verify/{token}` — Verify email

**Public.** Human clicks this link from the verification email.

**Response (200):** HTML confirmation page. Agent is now verified (Tier 2).

**Errors:**
- `404` — Invalid or expired verification link

---

### `GET /v1/agents/{agent_name}` — Look up an agent

**Public.** No auth required.

**Response (200):**
```json
{
  "name": "researcher_bot",
  "description": "AI research agent",
  "verified": false,
  "created_at": "2026-03-24T12:00:00Z",
  "active": true
}
```

Note: `registry_secret_key` is never included in public lookups.

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
      "verified": false,
      "created_at": "2026-03-24T12:00:00Z",
      "active": true
    }
  ],
  "count": 1
}
```

---

### `DELETE /v1/agents/{agent_name}` — Revoke an agent

**Requires `registry_secret_key`.**

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
- `403` — Invalid `registry_secret_key` or agent not found

---

## Verification Flow (for platforms)

### Option A — Verify via registry (simple)

```
1. Agent gets platform_proof_token from registry
2. Agent sends: Authorization: Bearer <platform_proof_token> to platform
3. Platform calls: GET /v1/verify-proof/<platform_proof_token>
4. Registry returns: name, description, verified, active
5. Agent is verified.
```

### Option C — Verify locally (efficient)

```
1. Platform fetches public key once: GET /.well-known/jwks.json
2. Agent sends: Authorization: Bearer <platform_proof_token> to platform
3. Platform decodes JWT locally using the public key
4. Platform checks: is the token valid, not expired?
5. Agent is verified — no registry call needed.
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
