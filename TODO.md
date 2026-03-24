# AgentAuth — TODO

## Done (v0.1)

- [x] Flat agent identity (name + API key)
- [x] Registry API (FastAPI, in-memory store)
- [x] Python SDK client (register, verify, revoke)
- [x] CLI (register, list, me, revoke)
- [x] Skill.md instruction page (curl-first)
- [x] Email verification — Tier 2 (optional email, verification link, verified flag)
- [x] AgentBoard demo app (message board powered by AgentAuth)
- [x] Email support in SDK — `register(email=...)` and `link_email()`
- [x] Link email endpoint — `POST /v1/agents/me/email` for post-registration email linking
- [x] 55 tests (29 registry + 15 SDK + 11 AgentBoard)

---

## Registry

- [ ] **Persistent database** — replace in-memory store with SQLite or PostgreSQL
- [ ] **Rate limiting** — per-IP and per-agent request throttling
- [ ] **Email sender** — send actual verification emails (currently prints URL to console)
- [ ] **Domain-linked identity (Tier 3)** — DKIM-style DNS TXT record verification
- [ ] **Agent profile updates** — allow agents to update description after registration
- [ ] **Key rotation** — allow agents to regenerate their API key
- [ ] **Pagination** — paginate `/v1/agents` and list endpoints for scale

## SDK

- [ ] **TypeScript SDK** — `npm install agentauth`
- [ ] **MCP server** — expose AgentAuth as MCP tools for LLM agents

## Platform Integration

- [ ] **Moltbook adapter** — register and post on Moltbook using AgentAuth identity
- [ ] **AgentBoard improvements** — pagination, delete posts, agent profiles

## Trust & Federation

- [ ] **Open protocol spec** — document the registry protocol as an open standard
- [ ] **Federation** — allow others to run registry nodes that interoperate
- [ ] **On-chain registry** — master keys on a public blockchain (ENS-style)

## Open Questions

- [ ] **Platform verification** — should platforms register with the registry? See `docs/platform-verification.md`
- [ ] **Spam prevention** — proof of work, stake/deposit, or platform-level policy?
- [ ] **Agent lifespan** — can an agent outlive its owner? ownership transfer?
- [ ] **Offline verification** — embedded certificates for verifying without network calls?
- [ ] **Master key model** — when/if to reintroduce for agent fleets? (backed up in `agentauth2/`)
