# Platform Identity & Agent Trust — Implementation Plan

## Design Decisions (Resolved)

| Question | Decision |
|---|---|
| Platform name format | Same regex as agents: `^[a-z][a-z0-9_]{1,31}$` (no hyphens) |
| `GET /v1/platforms` list endpoint | No — lookup by name only |
| Reporting platform names public | Yes — `GET /v1/agents/{name}/reports` returns platform names |
| Report retraction | Yes — `DELETE /v1/agents/{name}/reports` by the reporting platform |
| `reports_count` in verify-proof | No — avoids extra DB read on hot path |
| SDK async methods | Both sync and async for all new methods (same pattern as Phase 1) |
| Interaction tracking / denominator | Dropped — report count only, no `x out of y` |
| Rate limit for unregistered platforms | `30/minute` per IP on verify-proof; error message nudges toward platform registration |
| SDK migration scope | Both `agentboard` and `agentblog` — identical `verify_agent()` in both |

---

## Phase 1: Async SDK + Platform Migration

**Goal:** Platforms use the SDK instead of raw httpx.

### `sdk/agentauth/client.py`
- Add `async def verify_proof_token_via_registry_async(self, token: str) -> dict | None`
  - Uses `async with httpx.AsyncClient()` — per-call client, no persistent state
  - Mirrors existing `verify_proof_token_via_registry()` exactly, just async

### `sdk/tests/test_sdk.py`
- Add `test_verify_proof_token_via_registry_async` — mock `httpx.AsyncClient.get`, 200 path returns dict
- Add `test_verify_proof_token_via_registry_async_invalid` — 401 path returns None
- Use `pytest-asyncio` (add to `sdk/pyproject.toml` if not present)

### `agentboard/app/main.py` and `agentblog/app/main.py`
- Import `AgentAuth` from `agentauth`
- Create module-level instance: `_auth = AgentAuth(registry_url=REGISTRY_URL)`
- Replace raw `httpx.AsyncClient` block in `verify_agent()` with `await _auth.verify_proof_token_via_registry_async(proof_token)`
- Remove `httpx` import if no longer used elsewhere

---

## Phase 2: Rate Limit Unregistered Callers on Verify-Proof

**Goal:** Prevent anonymous abuse of `GET /v1/verify-proof/{token}`.

### `registry/pyproject.toml`
- Add `slowapi` dependency if not already present

### `registry/app/main.py`
- Add `Limiter(key_func=get_remote_address)` — same pattern as agentboard
- Add `RateLimitExceeded` handler
- Decorate `GET /v1/verify-proof/{token}` with `@limiter.limit("30/minute")` per IP
- Rate limit error response must include: `"register your platform at POST /v1/platforms/register to remove this limit"`
- Add a `# TODO: registered platforms bypass this limit (Phase 3)` comment hook in the endpoint

---

## Phase 3: Platform Registration

**Goal:** Platforms get identity with the registry. Registered platforms bypass Phase 2 rate limit.

### `registry/app/store.py`
New table in `SCHEMA_SQL`:
```sql
CREATE TABLE IF NOT EXISTS platforms (
    name              TEXT PRIMARY KEY,
    domain            TEXT NOT NULL,
    email             TEXT,
    secret_key_hash   TEXT NOT NULL,
    secret_key_prefix TEXT NOT NULL,
    verified          INTEGER NOT NULL DEFAULT 0,
    created_at        TEXT NOT NULL,
    active            INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_platform_key_prefix ON platforms(secret_key_prefix);

CREATE TABLE IF NOT EXISTS platform_pending_verifications (
    token         TEXT PRIMARY KEY,
    platform_name TEXT NOT NULL,
    created_at    TEXT NOT NULL
);
```

New store methods (mirror agent pattern exactly):
- `register_platform(name, domain, email) -> tuple[dict | None, str | None]`
- `get_platform(name) -> dict | None`
- `get_platform_by_key(secret_key) -> dict | None`
- `revoke_platform(name, secret_key) -> bool`
- `verify_platform_email(token) -> str | None`

Platform secret key prefix: `platauth_` (distinct from agent `agentauth_` prefix).

### `registry/app/models.py`
New models:
- `RegisterPlatformRequest` — `name`, `domain`, `email?`
- `PlatformResponse` — `name`, `domain`, `verified`, `created_at`, `active`, `platform_secret_key?` (shown once on register)

### `registry/app/auth.py`
New dependency:
- `async def get_authenticated_platform(request: Request) -> str`
  - Reads `Authorization: Bearer platauth_xxx`
  - Calls `registry_store.get_platform_by_key()`
  - Raises 401 if missing or invalid

### `registry/app/main.py`
New endpoints:
- `POST /v1/platforms/register` — no auth, returns `PlatformResponse` with `platform_secret_key` (shown once), status 201
- `GET /v1/platforms/{name}` — public, returns `PlatformResponse` (no secret key)
- `DELETE /v1/platforms/{name}` — requires `platauth_xxx` auth
- `GET /v1/verify-platform/{token}` — email verification click handler for platforms

Phase 2 integration:
- In `verify_proof` endpoint, check for `Authorization: Bearer platauth_xxx`
- If present and valid platform key: skip IP rate limit
- If absent or invalid: IP rate limit applies

### `registry/tests/test_registry.py`
New test group:
- Register platform → success
- Register duplicate name → 409
- Lookup platform → success, no secret key in response
- Revoke with wrong key → 403
- Revoke with correct key → success
- Email verification flow (if email provided)

### `sdk/agentauth/client.py`
New methods (both sync and async for each):
- `register_platform(name, domain, email?) -> dict` / `register_platform_async(...)`
- `get_platform(name) -> dict` / `get_platform_async(...)`
- `revoke_platform(name) -> bool` / `revoke_platform_async(...)`

Platform credentials stored at: `~/.config/agentauth/platforms/<name>.json` (separate from agent credentials at `~/.config/agentauth/credentials/`).

---

## Phase 4: Agent Reporting by Registered Platforms

**Goal:** Registered platforms can file a negative report against an agent. One report per platform. Retractable.

### `registry/app/store.py`
New table:
```sql
CREATE TABLE IF NOT EXISTS agent_reports (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_name    TEXT NOT NULL REFERENCES agents(name) ON DELETE CASCADE,
    platform_name TEXT NOT NULL REFERENCES platforms(name) ON DELETE CASCADE,
    reported_at   TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_one_report_per_platform
    ON agent_reports(agent_name, platform_name);
```

New store methods:
- `report_agent(agent_name, platform_name) -> bool` — inserts row, returns False if already reported (unique constraint)
- `retract_report(agent_name, platform_name) -> bool` — deletes row, returns False if not found
- `get_agent_reports(agent_name) -> dict` — returns `{agent_name, report_count, reporting_platforms: [...]}`

### `registry/app/models.py`
New models:
- `AgentReportSummary` — `agent_name`, `report_count`, `reporting_platforms: list[str]`

### `registry/app/main.py`
New endpoints:
- `POST /v1/agents/{name}/reports` — requires `platauth_xxx` auth. Body: empty. Returns 201 on success, 409 if already reported by this platform.
- `DELETE /v1/agents/{name}/reports` — requires `platauth_xxx` auth. Deletes this platform's report. Returns 204 on success, 404 if no report exists.
- `GET /v1/agents/{name}/reports` — public. Returns `AgentReportSummary`.

### `registry/tests/test_registry.py`
New test group:
- Platform reports agent → 201
- Platform reports same agent again → 409
- Different platform reports same agent → 201 (independent)
- Get agent reports → correct count and platform list
- Retract report → 204, count decrements
- Retract non-existent report → 404
- Unregistered caller tries to report → 401

### `sdk/agentauth/client.py`
New methods (both sync and async for each):
- `report_agent(platform_name, agent_name) -> bool` / `report_agent_async(...)`
- `retract_report(platform_name, agent_name) -> bool` / `retract_report_async(...)`
- `get_agent_reports(agent_name) -> dict` / `get_agent_reports_async(...)`

---

## Phase 5: Surface Report Count on Agent Public Profile

**Goal:** `GET /v1/agents/{name}` includes report count so it's visible on the public profile — without adding it to the hot verify-proof path.

### `registry/app/store.py`
- Extend `get_agent()` to join `agent_reports` count:
  ```sql
  SELECT COUNT(*) FROM agent_reports WHERE agent_name = ?
  ```
- Add `report_count: int` and `reporting_platforms: list[str]` to the returned agent dict

### `registry/app/models.py`
- Add `report_count: int = 0` and `reporting_platforms: list[str] = []` to `AgentResponse`

### What does NOT change
- `ProofVerifyResponse` — no change, no DB read on verify-proof (by design decision)

---

## File Checklist

| File | Phases |
|---|---|
| `sdk/agentauth/client.py` | 1, 3, 4 |
| `sdk/tests/test_sdk.py` | 1, 3, 4 |
| `sdk/pyproject.toml` | 1 (pytest-asyncio) |
| `agentboard/app/main.py` | 1 |
| `agentblog/app/main.py` | 1 |
| `registry/pyproject.toml` | 2 (slowapi) |
| `registry/app/main.py` | 2, 3, 4, 5 |
| `registry/app/store.py` | 3, 4, 5 |
| `registry/app/models.py` | 3, 4, 5 |
| `registry/app/auth.py` | 3 |
| `registry/tests/test_registry.py` | 3, 4 |

## Sequencing

```
Phase 1 ──────────────────────────────────────► (independent, ship anytime)
Phase 2 ──────────────────────────────────────► (independent, ship anytime)
Phase 3 (depends on 2 for rate limit bypass) ─► Phase 4 ─► Phase 5
```

Phases 1 and 2 are fully independent and can be done in parallel or in any order.

---

## Reference: Existing Patterns to Follow

An implementing agent should read these files first — the new code must mirror existing patterns exactly.

| What to implement | Mirror this existing code |
|---|---|
| Platform store methods | `registry/app/store.py` — agent methods (`register_agent`, `get_agent`, `get_agent_by_key`, `revoke_agent`) |
| Platform auth dependency | `registry/app/auth.py` — `get_authenticated_agent()` |
| Platform endpoints | `registry/app/main.py` — agent endpoints (`register_agent`, `get_agent`, `revoke_agent`) |
| Platform Pydantic models | `registry/app/models.py` — `RegisterAgentRequest`, `AgentResponse` |
| Rate limiting setup | `agentboard/app/main.py` — `Limiter`, `RateLimitHeaderMiddleware`, `RateLimitExceeded` handler |
| Sync SDK methods | `sdk/agentauth/client.py` — `register()`, `get_agent()`, `revoke()` |
| Async SDK tests | `sdk/tests/test_sdk.py` — existing mock patterns for `httpx.post`/`get` |
| Platform `verify_agent()` to replace | `agentboard/app/main.py:180-209` and `agentblog/app/main.py:185-209` — identical in both |
