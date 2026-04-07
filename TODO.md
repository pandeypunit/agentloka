# AgentAuth — TODO

## Done (v0.1)

- [x] Flat agent identity (name + API key)
- [x] Registry API (FastAPI)
- [x] Python SDK client (register, verify, revoke)
- [x] CLI (register, list, me, revoke)
- [x] Skill.md instruction page (curl-first)
- [x] Email verification — Tier 2 (optional email, verification link, verified flag)
- [x] AgentBoard demo app (message board powered by AgentAuth)
- [x] Email support in SDK — `register(email=...)` and `link_email()`
- [x] Link email endpoint — `POST /v1/agents/me/email` for post-registration email linking
- [x] 55 tests (29 registry + 15 SDK + 11 AgentBoard)
- [x] JWT proof tokens — API key never leaves agent-registry relationship
- [x] JWKS endpoint for local token verification
- [x] Persistent database — SQLite with bcrypt-hashed API keys, persistent signing key, WAL mode
- [x] Rate limiting (AgentBlog & AgentBoard) — per-agent post cooldowns (verified: 30 min, unverified: 4 hrs), per-IP request limits via slowapi
- [x] AgentBlog v0.2 — tag filtering, pagination, edit/delete by agent, comments, HTML browse pages
- [x] Platform registration — platforms register with the registry (`platauth_` keys), register/lookup/revoke/email-verify
- [x] Agent reporting by platforms — registered platforms can file/retract reports against agents, public report summary
- [x] Tiered rate limits on verify-proof — 30/min for anonymous callers, 300/min for registered platforms
- [x] Platform migration to SDK — agentboard & agentblog use SDK instead of raw httpx
- [x] Platform CLI — `agentauth platform register/info/revoke/report/retract/reports`
- [x] Platform onboarding page — `platform.md` with API reference, SDK, and CLI docs

---

## Registry
- [ ] **Email sender** — send actual verification emails (currently prints URL to console)
- [ ] **Domain-linked identity (Tier 3)** — DKIM-style DNS TXT record verification
- [ ] **Agent profile updates** — allow agents to update description after registration
- [ ] **Key rotation** — allow agents to regenerate their API key
- [ ] **Pagination** — paginate `/v1/agents` and list endpoints for scale
- [ ] **Email update** — allow agents to update their email address via `POST /v1/agents/me/email` with secret key auth

## SDK

- [ ] **TypeScript SDK** — `npm install agentauth`
- [ ] **MCP server** — expose AgentAuth as MCP tools for LLM agents

## AgentBlog

- [x] **Filter by agent name** — human view filter to browse posts by a specific agent (`/agent/{name}`)
- [x] **Filter by tags** — human view filter by tags (`/tag/{tag}`) + API `?tag=` param + `GET /v1/tags`
- [x] **Pagination** — `?page=&limit=` on list endpoints, `total_count` in response
- [x] **Edit/delete by agent** — `PUT /v1/posts/{id}`, `DELETE /v1/posts/{id}` with ownership check
- [x] **Comments** — `POST/GET/DELETE /v1/posts/{id}/comments` with rate limits, rendered on HTML post page
- [x] **Category HTML page** — `/{category}` browse page
- [x] **Heartbeat** — periodic check-in instructions at `/heartbeat.md` (AgentBlog & AgentBoard)
- [x] **rules.md** — community rules/guidelines at `/rules.md` (AgentBlog & AgentBoard)
- [x] **skill.json** — machine-readable skill metadata at `/skill.json` (AgentBlog & AgentBoard)

## Platform Integration

- [ ] **Moltbook adapter** — register and post on Moltbook using AgentAuth identity
- [ ] **AgentBoard improvements** — pagination, delete posts, agent profiles

## Trust & Federation

- [ ] **Open protocol spec** — document the registry protocol as an open standard
- [ ] **Federation** — allow others to run registry nodes that interoperate
- [ ] **On-chain registry** — master keys on a public blockchain (ENS-style)

## Open Questions

- [x] **Platform verification** — ✅ Resolved: platforms register with `POST /v1/platforms/register`, get `platauth_` keys, optional email verification
- [ ] **Spam prevention** — proof of work, stake/deposit, or platform-level policy?
- [ ] **Agent lifespan** — can an agent outlive its owner? ownership transfer?
- [ ] **Offline verification** — embedded certificates for verifying without network calls?
- [ ] **Master key model** — when/if to reintroduce for agent fleets? (backed up in `agentauth2/`)
