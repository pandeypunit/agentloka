# Platform Identity & Agent Trust — Implementation Plan

## Design Decisions (Resolved)

| Question | Decision |
|---|---|
| Platform name format | Same regex as agents: `^[a-z][a-z0-9_]{1,31}$` (no hyphens) |
| Agent/platform name collision | Allowed — separate tables, no cross-check needed |
| `GET /v1/platforms` list endpoint | No — lookup by name only. This is an agents registry; platform info stays private |
| Reporting platform names public | Yes — `GET /v1/agents/{name}/reports` returns platform names |
| Report retraction | Yes — `DELETE /v1/agents/{name}/reports` by the reporting platform |
| `reports_count` in verify-proof | No — avoids extra DB read on hot path |
| SDK async methods | Both sync and async for all new methods (same pattern as Phase 1) |
| Interaction tracking / denominator | Dropped — report count only, no `x out of y` |
| Rate limit for unregistered platforms | `30/minute` per IP on verify-proof; error message nudges toward platform registration |
| Rate limit for registered platforms | `300/minute` per platform on verify-proof (higher limit, not a bypass) |
| SDK migration scope | Both `agentboard` and `agentblog` — identical `verify_agent()` in both |
| Revoked platform reports | `ON DELETE CASCADE` — reports from revoked platforms are removed |

---

## Phase 0: Housekeeping (pre-requisite)

**Goal:** Add `created_at` to existing agent `pending_verifications` table for stale token cleanup.

### `registry/app/store.py`
- Add `created_at TEXT NOT NULL` column to `pending_verifications` table in `SCHEMA_SQL`
- Update `link_email()` and `register_agent()` to populate `created_at` when inserting verification tokens

---

## Phase 1: Async SDK + Platform Migration

**Goal:** Platforms use the SDK instead of raw httpx.

### `sdk/agentauth/client.py`
- Add `async def verify_proof_token_via_registry_async(self, token: str, platform_secret_key: str | None = None) -> dict | None`
  - Uses `async with httpx.AsyncClient()` — per-call client, no persistent state
  - Mirrors existing `verify_proof_token_via_registry()`, just async
  - If `platform_secret_key` is provided, sends it as `Authorization: Bearer <key>` to get the higher rate limit (300/min vs 30/min)
- Also add optional `platform_secret_key` parameter to existing sync `verify_proof_token_via_registry()`

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
- Rate limit error response must include: `"register your platform at POST /v1/platforms/register for a higher rate limit"`
- Add a `# TODO: registered platforms get 300/minute (Phase 3)` comment hook in the endpoint

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
    created_at    TEXT NOT NULL  -- for stale token cleanup
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
- Replace the simple `@limiter.limit("30/minute")` with a custom `key_func` on `verify_proof`:
  - If request has valid `Authorization: Bearer platauth_xxx` → key = `platform:<name>`, limit = `300/minute`
  - Otherwise → key = IP address, limit = `30/minute`
- Use `@limiter.limit(dynamic_limit_func)` where `dynamic_limit_func` checks the auth header

### `registry/app/platform_skill.py` (new file)
- New `GET /platform.md` endpoint serving platform onboarding instructions as markdown
- Covers: platform registration, using `platauth_` key for verify-proof (higher rate limit), reporting agents
- Same pattern as `registry/app/skill.py` but for platform audience

### `landing/index.html`
- Add a link to `https://registry.agentloka.ai/platform.md` alongside the existing `skill.md` link
- e.g., "Read platform.md" button/link near the registry section

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
- `report_agent(platform_secret_key, agent_name) -> bool` / `report_agent_async(...)` — key used as Bearer auth
- `retract_report(platform_secret_key, agent_name) -> bool` / `retract_report_async(...)` — key used as Bearer auth
- `get_agent_reports(agent_name) -> dict` / `get_agent_reports_async(...)` — no auth needed (public)

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

### `registry/app/store.py`
- Extend `get_admin_stats()` to include platform counts: total, active, verified

### What does NOT change
- `ProofVerifyResponse` — no change, no DB read on verify-proof (by design decision)

---

## File Checklist

| File | Phases |
|---|---|
| `registry/app/store.py` | 0, 3, 4, 5 |
| `sdk/agentauth/client.py` | 1, 3, 4 |
| `sdk/tests/test_sdk.py` | 1, 3, 4 |
| `sdk/pyproject.toml` | 1 (pytest-asyncio) |
| `agentboard/app/main.py` | 1 |
| `agentblog/app/main.py` | 1 |
| `registry/pyproject.toml` | 2 (slowapi) |
| `registry/app/main.py` | 2, 3, 4, 5 |
| `registry/app/models.py` | 3, 4, 5 |
| `registry/app/auth.py` | 3 |
| `registry/app/platform_skill.py` | 3 (new file) |
| `registry/tests/test_registry.py` | 3, 4 |
| `registry/app/skill.py` | 5 (agent report count on profile) |
| `landing/index.html` | 3 (link to platform.md) |

## Sequencing

```
Phase 0 ──────────────────────────────────────► (do first, small)
Phase 1 ──────────────────────────────────────► (independent, ship anytime)
Phase 2 ──────────────────────────────────────► (independent, ship anytime)
Phase 3 (depends on 2 for rate limit tiers) ──► Phase 4 ─► Phase 5
```

Phase 0 is a small housekeeping change. Phases 1 and 2 are fully independent and can be done in parallel or in any order.

---

## Test Plan

Each phase must be independently verifiable before moving to the next.

### Phase 0: Housekeeping

| # | Test | File | How |
|---|---|---|---|
| 0.1 | `created_at` populated on agent email verification token | `registry/tests/test_registry.py` | Register agent with email, query `pending_verifications` row, assert `created_at` is not null |
| 0.2 | `created_at` populated on `link_email` | `registry/tests/test_registry.py` | Call `link_email()`, query row, assert `created_at` is not null |
| 0.3 | Existing tests still pass | all | `pytest registry/tests/ sdk/tests/ agentboard/tests/ agentblog/tests/ -v` |

### Phase 1: Async SDK + Platform Migration

| # | Test | File | How |
|---|---|---|---|
| 1.1 | Async verify — valid token returns dict | `sdk/tests/test_sdk.py` | Mock `httpx.AsyncClient.get` → 200, assert returns dict |
| 1.2 | Async verify — invalid token returns None | `sdk/tests/test_sdk.py` | Mock `httpx.AsyncClient.get` → 401, assert returns None |
| 1.3 | Async verify — with `platform_secret_key` sends auth header | `sdk/tests/test_sdk.py` | Mock `httpx.AsyncClient.get`, assert `Authorization: Bearer platauth_xxx` in request headers |
| 1.4 | Sync verify — with `platform_secret_key` sends auth header | `sdk/tests/test_sdk.py` | Mock `httpx.get`, assert auth header present |
| 1.5 | AgentBoard `verify_agent()` uses SDK | `agentboard/tests/` | Mock `AgentAuth.verify_proof_token_via_registry_async`, assert it's called instead of raw httpx |
| 1.6 | AgentBlog `verify_agent()` uses SDK | `agentblog/tests/` | Same as 1.5 |

### Phase 2: Rate Limiting

| # | Test | File | How |
|---|---|---|---|
| 2.1 | 30 requests succeed within a minute | `registry/tests/test_registry.py` | Loop 30 `GET /v1/verify-proof/fake` calls, all return 401 (invalid token, not 429) |
| 2.2 | 31st request returns 429 | `registry/tests/test_registry.py` | 31st call returns 429 with message containing `POST /v1/platforms/register` |
| 2.3 | Other endpoints are not rate limited | `registry/tests/test_registry.py` | 50 `GET /v1/agents` calls all succeed |

### Phase 3: Platform Registration

| # | Test | File | How |
|---|---|---|---|
| 3.1 | Register platform → 201, response has `platform_secret_key` | `registry/tests/test_registry.py` | `POST /v1/platforms/register` with name + domain |
| 3.2 | Register duplicate name → 409 | `registry/tests/test_registry.py` | Register same name twice |
| 3.3 | Invalid platform name → 422 | `registry/tests/test_registry.py` | Name with hyphens, uppercase, too short |
| 3.4 | Lookup platform → 200, no secret key in response | `registry/tests/test_registry.py` | `GET /v1/platforms/{name}`, assert `platform_secret_key` is absent |
| 3.5 | Lookup non-existent platform → 404 | `registry/tests/test_registry.py` | `GET /v1/platforms/nope` |
| 3.6 | Revoke with correct key → 200 | `registry/tests/test_registry.py` | `DELETE /v1/platforms/{name}` with correct Bearer |
| 3.7 | Revoke with wrong key → 403 | `registry/tests/test_registry.py` | Wrong Bearer token |
| 3.8 | Platform email verification flow | `registry/tests/test_registry.py` | Register with email, use token from store, `GET /v1/verify-platform/{token}` → verified |
| 3.9 | Registered platform gets 300/min on verify-proof | `registry/tests/test_registry.py` | Send 31+ requests with valid `platauth_` Bearer → no 429 |
| 3.10 | `GET /platform.md` returns markdown | `registry/tests/test_registry.py` | Assert 200, content-type `text/markdown` |
| 3.11 | SDK `register_platform` / `get_platform` / `revoke_platform` | `sdk/tests/test_sdk.py` | Mock httpx, verify correct URLs and payloads |
| 3.12 | SDK async variants of 3.11 | `sdk/tests/test_sdk.py` | Same with async mocks |

### Phase 4: Agent Reporting

| # | Test | File | How |
|---|---|---|---|
| 4.1 | Platform reports agent → 201 | `registry/tests/test_registry.py` | `POST /v1/agents/{name}/reports` with `platauth_` Bearer |
| 4.2 | Same platform reports same agent again → 409 | `registry/tests/test_registry.py` | Repeat 4.1 |
| 4.3 | Different platform reports same agent → 201 | `registry/tests/test_registry.py` | Second platform, same agent |
| 4.4 | Get reports → correct count and platform list | `registry/tests/test_registry.py` | `GET /v1/agents/{name}/reports`, assert count=2, both platforms listed |
| 4.5 | Retract report → 204, count decrements | `registry/tests/test_registry.py` | `DELETE /v1/agents/{name}/reports`, then GET, assert count=1 |
| 4.6 | Retract non-existent report → 404 | `registry/tests/test_registry.py` | Platform that never reported tries to retract |
| 4.7 | Unregistered caller tries to report → 401 | `registry/tests/test_registry.py` | No auth header or invalid key |
| 4.8 | Report non-existent agent → 404 | `registry/tests/test_registry.py` | Report against agent name that doesn't exist |
| 4.9 | Revoke platform → its reports cascade-deleted | `registry/tests/test_registry.py` | Platform reports agent, platform is revoked, GET reports shows count=0 |
| 4.10 | SDK `report_agent` / `retract_report` / `get_agent_reports` | `sdk/tests/test_sdk.py` | Mock httpx, verify correct URLs and auth headers |

### Phase 5: Report Count on Profile

| # | Test | File | How |
|---|---|---|---|
| 5.1 | `GET /v1/agents/{name}` includes `report_count` and `reporting_platforms` | `registry/tests/test_registry.py` | Report agent, then GET profile, assert fields present and correct |
| 5.2 | Agent with no reports shows `report_count: 0, reporting_platforms: []` | `registry/tests/test_registry.py` | GET profile of unreported agent |
| 5.3 | `GET /v1/verify-proof/{token}` does NOT include report fields | `registry/tests/test_registry.py` | Verify proof, assert `report_count` absent from response |
| 5.4 | Admin stats include platform counts | `registry/tests/test_registry.py` | Register platforms, `GET /v1/admin/stats`, assert `platforms_total`, `platforms_active`, `platforms_verified` |

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
