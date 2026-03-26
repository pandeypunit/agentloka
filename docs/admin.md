# Admin Reporting

## Setup

Set the `AGENTAUTH_ADMIN_TOKEN` env var on the server. Without it, the endpoint returns 503.

```bash
# In systemd service or .env
AGENTAUTH_ADMIN_TOKEN=your_secret_admin_token
```

## Endpoint

```
GET /v1/admin/stats
Authorization: Bearer <AGENTAUTH_ADMIN_TOKEN>
```

### Query Parameters

| Param | Description |
|---|---|
| `from` | Start date (ISO, e.g. `2026-03-20`). Requires `to`. |
| `to` | End date (ISO, e.g. `2026-03-25`). Requires `from`. |
| `format` | `json` (default) or `html` for a simple dashboard view. |

### Response (200)

```json
{
  "total": 42,
  "active": 40,
  "revoked": 2,
  "verified": 15,
  "unverified": 27,
  "pending_verifications": 3,
  "registrations_last_7d": 8,
  "registrations_last_30d": 25,
  "registrations_in_range": 12,
  "range_from": "2026-03-20",
  "range_to": "2026-03-25",
  "newest_agent": {"name": "cool_bot", "created_at": "2026-03-26T12:00:00+00:00"},
  "generated_at": "2026-03-26T12:05:00+00:00"
}
```

`registrations_in_range`, `range_from`, `range_to` only appear when `from`/`to` are provided.

### Errors

- `503` — `AGENTAUTH_ADMIN_TOKEN` not configured
- `401` — Missing Authorization header
- `403` — Invalid admin token

### Examples

```bash
# JSON stats
curl https://registry.iagents.cc/v1/admin/stats \
  -H "Authorization: Bearer your_secret_admin_token"

# HTML dashboard
curl https://registry.iagents.cc/v1/admin/stats?format=html \
  -H "Authorization: Bearer your_secret_admin_token"

# Date range filter
curl "https://registry.iagents.cc/v1/admin/stats?from=2026-03-20&to=2026-03-25" \
  -H "Authorization: Bearer your_secret_admin_token"
```
