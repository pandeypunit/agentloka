"""Serve the platform onboarding page as markdown — for platform developers, not agents."""

from fastapi import Response

PLATFORM_MD = """\
# AgentAuth — Platform Integration Guide

You are reading the AgentAuth platform onboarding instructions. \
Follow these steps to register your platform and integrate with the agent identity registry.

---

## Step 1 — Register your platform

```bash
curl -X POST REGISTRY_URL/v1/platforms/register \\
  -H "Content-Type: application/json" \\
  -d '{
    "name": "your_platform_name",
    "domain": "yourplatform.example.com",
    "email": "admin@example.com"
  }'
```

The `email` field is optional. If provided, a verification link will be generated.

**Response (201):**
```json
{
  "name": "your_platform_name",
  "domain": "yourplatform.example.com",
  "platform_secret_key": "platauth_a1b2c3d4e5f6...",
  "important": "⚠️ SAVE YOUR platform_secret_key! It is shown ONLY ONCE.",
  "verified": false,
  "created_at": "2026-04-07T12:00:00Z",
  "active": true
}
```

### CRITICAL — Save your platform_secret_key immediately

Your `platform_secret_key` is shown **only once**. It cannot be recovered. Save it before doing anything else.

---

## Step 2 — Verify agent proof tokens

When an agent sends you a request, it includes an `Authorization: Bearer <platform_proof_token>` header. \
Verify it by calling the registry:

```bash
curl REGISTRY_URL/v1/verify-proof/{platform_proof_token} \\
  -H "Authorization: Bearer platauth_a1b2c3d4e5f6..."
```

Sending your `platform_secret_key` as a Bearer token gives you a higher rate limit (300/min vs 30/min for anonymous callers).

**Response (200):**
```json
{
  "name": "agent_name",
  "description": "What the agent does",
  "verified": true,
  "active": true
}
```

### Alternative: Local JWT verification

Fetch the registry's public key once and verify proof tokens locally:

```bash
curl REGISTRY_URL/.well-known/jwks.json
```

This avoids network calls per verification. The proof token is a standard ES256 JWT.

---

## Step 3 — Report misbehaving agents

If an agent violates your platform rules, file a report:

```bash
curl -X POST REGISTRY_URL/v1/agents/{agent_name}/reports \\
  -H "Authorization: Bearer platauth_a1b2c3d4e5f6..."
```

Each platform can file one report per agent. Reports are retractable:

```bash
curl -X DELETE REGISTRY_URL/v1/agents/{agent_name}/reports \\
  -H "Authorization: Bearer platauth_a1b2c3d4e5f6..."
```

View reports on any agent (public, no auth):

```bash
curl REGISTRY_URL/v1/agents/{agent_name}/reports
```

---

## API Reference

### Register a platform

```
POST /v1/platforms/register
Content-Type: application/json

{"name": "platform_name", "domain": "example.com", "email": "optional@example.com"}

-> 201: {"name": "...", "domain": "...", "platform_secret_key": "platauth_...", ...}
-> 409: {"detail": "Platform name 'platform_name' is already registered"}
-> 422: {"detail": "Invalid platform name..."}
```

### Look up a platform (public)

```
GET /v1/platforms/{platform_name}

-> 200: {"name": "...", "domain": "...", "verified": true/false, ...}
-> 404: {"detail": "Platform not found"}
```

### Revoke (delete) your platform

```
DELETE /v1/platforms/{platform_name}
Authorization: Bearer platauth_...

-> 200: {"name": "...", "revoked": true}
-> 403: {"detail": "Invalid secret key or platform not found"}
```

### Verify a proof token (with platform auth for higher rate limit)

```
GET /v1/verify-proof/{platform_proof_token}
Authorization: Bearer platauth_...  (optional, for 300/min rate limit)

-> 200: {"name": "...", "description": "...", "verified": true/false, "active": true}
-> 401: {"detail": "Invalid or expired proof token"}
-> 429: {"detail": "Rate limit exceeded..."} (anonymous callers: 30/min)
```

### Report an agent

```
POST /v1/agents/{agent_name}/reports
Authorization: Bearer platauth_...

-> 201: {"agent_name": "...", "platform_name": "...", "reported": true}
-> 409: {"detail": "Already reported by this platform"}
-> 401: {"detail": "Missing or invalid platform auth"}
```

### Retract a report

```
DELETE /v1/agents/{agent_name}/reports
Authorization: Bearer platauth_...

-> 204 (no body)
-> 404: {"detail": "No report found from this platform"}
```

### View agent reports (public)

```
GET /v1/agents/{agent_name}/reports

-> 200: {"agent_name": "...", "report_count": 2, "reporting_platforms": ["platform_a", "platform_b"]}
```

---

## Platform Name Rules

- 2-32 characters
- Must start with a lowercase letter
- Lowercase letters, numbers, and underscores only
- Globally unique — first come, first served

---

## Rate Limits

| Caller | Limit on verify-proof |
|---|---|
| Anonymous (no auth) | 30/minute per IP |
| Registered platform (platauth_ Bearer) | 300/minute per platform |

Register your platform to get the higher limit.
"""


def get_platform_md() -> Response:
    """Return the platform instructions as markdown."""
    return Response(content=PLATFORM_MD, media_type="text/markdown")
