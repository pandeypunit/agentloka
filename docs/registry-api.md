# AgentAuth Registry API Specification

**Base URL:** `https://registry.agentauth.dev/v1` (production, future)
**Local dev:** `http://localhost:8000/v1`

---

## Overview

The registry is the central trust anchor. It stores master public keys and agent registrations. Platforms query it to verify agent identity.

Two types of callers:
- **Owners** — register master keys and agents (authenticated via signature)
- **Platforms** — look up keys to verify agents (unauthenticated, read-only)

---

## Authentication

The registry uses **Ed25519 signature-based auth**, not API keys.

For write operations, the caller signs a request payload with their master private key. The registry verifies the signature against the registered public key.

For the initial `POST /v1/keys` (bootstrapping), the registry accepts the public key on trust (Tier 1 — pseudonymous). No prior relationship needed.

### Signature format

Write requests include these headers:

```
X-AgentAuth-PublicKey: <hex-encoded master public key>
X-AgentAuth-Signature: <hex-encoded Ed25519 signature of request body>
X-AgentAuth-Timestamp: <ISO 8601 UTC timestamp>
```

The signed message is: `{timestamp}\n{request_body}`

Timestamp must be within 5 minutes of server time to prevent replay attacks.

---

## Endpoints

### `POST /v1/keys` — Register a master key

Register a new master public key with the registry. This is the bootstrapping step — no prior auth needed.

**Request:**
```json
{
  "public_key": "<hex-encoded 32-byte Ed25519 public key>",
  "label": "punit-personal"
}
```

**Response (201):**
```json
{
  "key_id": "k_abc123",
  "public_key": "<hex>",
  "label": "punit-personal",
  "created_at": "2026-03-24T12:00:00Z"
}
```

**Errors:**
- `409` — Key already registered
- `422` — Invalid key format

---

### `GET /v1/keys/{key_id}` — Look up a master key

Public endpoint. Platforms call this to verify an agent's master key.

**Response (200):**
```json
{
  "key_id": "k_abc123",
  "public_key": "<hex>",
  "label": "punit-personal",
  "created_at": "2026-03-24T12:00:00Z",
  "agent_count": 3
}
```

**Errors:**
- `404` — Key not found

---

### `GET /v1/keys?public_key={hex}` — Look up by public key

Alternative lookup by public key hex instead of key_id.

**Response (200):** Same as above.

---

### `DELETE /v1/keys/{key_id}` — Revoke a master key

**Authenticated.** Revokes the master key and all agents under it.

**Headers:** Signature headers (signed with the master key being revoked)

**Response (200):**
```json
{
  "revoked": true,
  "agents_revoked": 3
}
```

---

### `POST /v1/agents` — Register an agent

**Authenticated.** Register a new agent under a master key.

**Headers:** Signature headers (signed with master key)

**Request:**
```json
{
  "agent_name": "researcher_bot",
  "agent_public_key": "<hex-encoded agent public key>",
  "master_public_key": "<hex-encoded master public key>",
  "description": "AI research agent"
}
```

**Response (201):**
```json
{
  "agent_name": "researcher_bot",
  "agent_public_key": "<hex>",
  "master_public_key": "<hex>",
  "description": "AI research agent",
  "created_at": "2026-03-24T12:00:00Z"
}
```

**Errors:**
- `409` — Agent name already taken
- `403` — Signature verification failed
- `404` — Master key not registered

---

### `GET /v1/agents/{agent_name}` — Look up an agent

Public endpoint. Platforms call this to verify an agent.

**Response (200):**
```json
{
  "agent_name": "researcher_bot",
  "agent_public_key": "<hex>",
  "master_public_key": "<hex>",
  "description": "AI research agent",
  "created_at": "2026-03-24T12:00:00Z",
  "active": true
}
```

**Errors:**
- `404` — Agent not found

---

### `GET /v1/agents?master_public_key={hex}` — List agents by master key

Public endpoint. List all agents under a master key.

**Response (200):**
```json
{
  "agents": [
    {
      "agent_name": "researcher_bot",
      "agent_public_key": "<hex>",
      "description": "AI research agent",
      "created_at": "2026-03-24T12:00:00Z",
      "active": true
    }
  ],
  "count": 1
}
```

---

### `DELETE /v1/agents/{agent_name}` — Revoke an agent

**Authenticated.** Signed with the master key that owns the agent.

**Response (200):**
```json
{
  "agent_name": "researcher_bot",
  "revoked": true
}
```

---

## Verification Flow (for platforms)

When a platform receives a registration request from an agent:

```
1. Agent sends: agent_name + agent_public_key + signature
2. Platform calls: GET /v1/agents/{agent_name}
3. Registry returns: agent_public_key + master_public_key + active status
4. Platform checks:
   a. Does agent_public_key match what the agent sent? ✓
   b. Is the agent active? ✓
   c. Is the signature valid against the agent_public_key? ✓
5. Agent is verified.
```
