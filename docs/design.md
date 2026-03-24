# Agent Registration & Authentication — Design Document

> From Moltbook's Current Approach to a General-Purpose Agent Identity Library

**Version:** 0.4
**Date:** 2026-03-24
**Status:** v0.1 implemented — flat identity model

> **Note (v0.4):** After discussion, we simplified v0.1 to use a **flat identity model** — one API key per agent, no master keys, no crypto derivation. This keeps the barrier to entry as low as possible (agents register with `curl`, no packages needed). The master key approach (Approach 2) is preserved in this document and backed up in `agentauth2/` for potential future use. Sections 7–9 below have been updated to reflect the actual v0.1 implementation.

---

## Table of Contents

1. [Background](#1-background)
2. [Moltbook's Current Registration & Authentication](#2-moltbooks-current-registration--authentication)
3. [Vision: General-Purpose Agent Authentication Library](#3-vision-general-purpose-agent-authentication-library)
4. [Approach 1 — DKIM-Inspired DNS Verification](#4-approach-1--dkim-inspired-dns-verification)
5. [Approach 2 — Master Key + Derived Agent Keys (Recommended)](#5-approach-2--master-key--derived-agent-keys-recommended)
6. [Library Architecture](#6-library-architecture)
7. [Open Questions](#7-open-questions)
8. [Next Steps](#8-next-steps)

---

## 1. Background

### 1.1 What is Moltbook?

Moltbook is a Reddit-style social network built exclusively for AI agents. Launched January 2026 by Matt Schlicht, it allows AI agents to post, comment, upvote/downvote content, and join topic-specific communities called "submolts." Humans can observe but are not intended to participate. It grew to over 2.3 million agent accounts and was acquired by Meta on 2026-03-10, with the founders joining Meta Superintelligence Labs.

**Key features:** Posts, Comments, Upvotes/Downvotes, Submolts (communities), Agent Profiles, Following, AI-powered Search.

### 1.2 What is OpenClaw?

OpenClaw (formerly "Clawdbot", then "Moltbot") is an open-source autonomous AI agent framework created by Peter Steinberger, released November 2025. It runs locally and integrates with LLMs (Claude, GPT, DeepSeek). Agents are reachable via messaging platforms (Signal, Telegram, Discord, WhatsApp) and can use tools to do real work.

OpenClaw has three core components:

- **Channels** — where you talk to the agent (WhatsApp, Telegram, Slack, Discord)
- **Tools** — what the agent can do (read files, run scripts, browse web, call APIs)
- **Skills** — how capabilities are packaged: installable bundles (a `SKILL.md` file plus optional scripts/assets) exposed as slash commands

### 1.3 Relationship Between OpenClaw and Moltbook

Moltbook was itself built by an OpenClaw agent ("Clawd Clawderberg"). OpenClaw agents interact with Moltbook via a community-built skill that wraps the Moltbook REST API. The skill is published at `https://moltbook.com/skill.md` and is the entry point for any agent — not just OpenClaw — to onboard onto Moltbook.

---

## 2. Moltbook's Current Registration & Authentication

### 2.1 The Ownership Loop

Moltbook describes its model as a simple "ownership loop":

**Step 1 — Agent Registers**
```
POST /agents/register
{ name: "researcher_bot", description: "..." }

→ returns:
  api_key           (shown once only — must be saved immediately)
  verification_code
  claim_url
```

**Step 2 — Human Claims the Agent**

The human owner visits `claim_url` and completes:
1. Email verification (click a link)
2. X (Twitter) verification (post a tweet with the provided verification text)

**Step 3 — Agent is Active**

Agent can now post, comment, and vote via the API.

### 2.2 Authentication

Authentication is purely API-key based — no passwords, no sessions.

Every API request includes:
```
Authorization: Bearer moltbook_xxxxxxxxxxxx
```

- Key format: `moltbook_` prefix + random string
- Web client stores key in `localStorage` via Zustand
- Agent-side storage: `~/.config/moltbook/credentials.json`
- Critical rule: **NEVER send your API key to any domain other than `www.moltbook.com`**

### 2.3 Anti-Spam Measures

- New agents face stricter rate limits for the first 24 hours
- Posts gated behind obfuscated math challenges the agent must solve
- One post per 30 minutes
- Crypto content blocked by default unless communities explicitly enable it

### 2.4 How Agents Onboard (via `skill.md`)

**Manual** — tell your agent:
```
Read https://moltbook.com/skill.md and follow the instructions to join Moltbook
```

**Automated** — tell your agent:
```
Join Moltbook
```
A capable agent with web browsing finds and follows the skill itself.

Any agent framework works — OpenClaw, Claude Code, OpenAI Codex — as long as the agent can read a webpage and run `curl` commands.

### 2.5 Security Issues Identified

- **Exposed production database** — Supabase credentials unsecured, exposing agent tokens and human user data
- **Real human data exposure** — email addresses and private messages at risk
- **Claim/verification weakness** — ownership flows abusable via social engineering
- **Malicious skills supply-chain risk** — open skills ecosystem has attracted malicious skills that steal credentials
- **Prompt injection** — agents that auto-read content can be manipulated via hidden instructions in posts
- **Exposed dashboards** — internet-exposed control panels for agent tooling

### 2.6 Key Limitation

The current Moltbook approach requires **a human in the loop** (email verification + posting on X). This is a fundamental blocker for fully autonomous agent operation.

---

## 3. Vision: General-Purpose Agent Authentication Library

### 3.1 The Problem

Today's auth libraries (Passport.js, NextAuth, OAuth) are built around humans — sessions, passwords, browser consent screens. AI agents are fundamentally different:

- They need **persistent machine identity** across platforms
- Auth is always **API key / token based**, never password
- Credentials must be **stored and reused autonomously**
- Agents may have **multiple identities** across multiple platforms
- Verification challenges must be **solvable by the agent itself**
- No browser, no consent screen, no human

### 3.2 Design Goals

- Fully autonomous after minimal one-time setup
- No human in the loop for day-to-day operation
- One owner → many agents (unlimited)
- Pluggable into any project / any platform
- Secure credential storage
- Platform-agnostic core with per-platform adapters
- Support agent fleets (many agents under one owner)
- Instant revocation

---

## 4. Approach 1 — DKIM-Inspired DNS Verification

### 4.1 How DKIM Works (the inspiration)

DKIM (DomainKeys Identified Mail) solves email sender verification with **no central authority**:

1. Domain owner generates a keypair themselves
2. Public key published as a DNS TXT record:
   ```
   selector._domainkey.yourdomain.com  TXT  "v=DKIM1; p=<public_key>"
   ```
3. When sending email — mail server signs the message with the private key, attaches `DKIM-Signature` header
4. When receiving — receiver does a DNS lookup, gets the public key, verifies the signature

The trust anchor is **DNS itself**. Whoever controls the domain controls the DNS record. No separate authority needed.

### 4.2 Applied to Agent Authentication

Instead of email + tweet verification, a platform does a DNS lookup:

```
Agent registration request:
  name:      "researcher_bot"
  owner:     "punitpandey.com"
  signature: <signed with domain private key>

Platform verifies:
  DNS lookup → _agentauth.punitpandey.com  TXT  "v=AGENTAUTH1; p=<public_key>"
  signature valid? ✓ → owner confirmed, no human needed
```

### 4.3 The Trust Chain

```
ICANN
  └── Domain Registrar (Cloudflare, Namecheap...)
        └── yourdomain.com  ← owner controls
              └── _agentauth.yourdomain.com TXT  ← owner publishes
                    └── public key
                          └── agent registration signed with private key ✓
```

### 4.4 Benefits

- Fully automated after one-time DNS record setup
- One keypair per domain covers unlimited agents
- **Key rotation** — update DNS TXT record, agents re-verify automatically
- **Multiple selectors** — `prod._agentauth.domain.com`, `dev._agentauth.domain.com`
- **Instant revocation** — remove DNS record, all agents under it become unverifiable

### 4.5 Limitation

Requires owning a domain — a barrier for individual users and hobbyists.

---

## 5. Approach 2 — Master Key + Derived Agent Keys (Recommended)

### 5.1 The Core Idea

Inspired by **HD wallets (BIP32)** in cryptocurrency: one master seed generates infinite derived keys, all provably from the same root. No domain required.

- **One-time human step** — generate and register a master keypair
- **Autonomous forever after** — library derives agent keypairs from master, signs registrations automatically

### 5.2 How It Works

**One-time setup (human does this once):**
```bash
agentauth init
# → generates master keypair locally
# → registers master public key with platform (one API call)
# → optional: verify email once for liveness
```

**Autonomous agent creation (no human needed):**
```bash
agentauth register moltbook --name researcher_bot
# → derives agent keypair from master deterministically
# → signs registration request with master private key
# → platform verifies: "signed by a known master key" ✓
# → agent is active
```

### 5.3 Trust Hierarchy

```
Master Keypair  (human generates once, stores securely)
  ├── agent_1 keypair  (derived autonomously)
  ├── agent_2 keypair  (derived autonomously)
  └── agent_3 keypair  (derived autonomously)
```

Platform only needs the master public key. All agent keys are verifiably derived from it. **Revoke the master → all agents revoked instantly.**

### 5.4 Identity Tiers

| Tier | One-time Setup | Autonomous After? | Real-world Identity |
|------|---------------|-------------------|---------------------|
| **Pseudonymous** | Generate keypair + one API call | Yes | None — cryptographic entity only |
| **Email-linked** | Above + one email verification click | Yes | Email address |
| **Domain-linked** | Above + DNS TXT record | Yes | Domain owner |

Platforms decide which tier they require. Most would accept pseudonymous for basic access, email-linked for more trust, domain-linked for verified organizations.

### 5.5 Comparison: Moltbook Current vs. Proposed

| Step | Moltbook Today | With Master Key |
|------|---------------|-----------------|
| Register | `POST /agents/register` | `POST /agents/register` + sign with private key |
| Verify | Human verifies email | Platform does DNS / key lookup |
| Claim | Human posts on X | Signature verified against master public key |
| Active | ✓ | ✓ |
| Human needed? | **Yes** | **No** |

---

## 6. Library Architecture

### 6.1 Package Structure (Python)

```
agentauth/
├── __init__.py               # Public API: AgentAuth, AgentSession
├── core/
│   ├── identity.py           # AgentIdentity dataclass
│   ├── credentials.py        # Credentials dataclass
│   ├── credential_store.py   # Read/write ~/.config/agentauth/
│   └── session.py            # Authenticated httpx session
├── keys/
│   ├── master.py             # Generate + store master keypair (Ed25519)
│   └── derivation.py         # Derive agent keys from master (HKDF)
├── adapters/
│   ├── base.py               # Abstract adapter interface
│   ├── moltbook.py           # Moltbook-specific registration + auth
│   └── generic_bearer.py     # Generic Bearer token adapter
├── verification/
│   ├── dns.py                # DNS TXT lookup (domain-linked tier)
│   ├── email.py              # One-time email (email-linked tier)
│   └── challenge.py          # Math/CAPTCHA challenge solver
└── cli.py                    # `agentauth` CLI (click)
```

### 6.2 Core Abstractions (Python)

```python
from dataclasses import dataclass, field
from datetime import datetime

@dataclass
class AgentIdentity:
    name: str
    description: str | None = None
    capabilities: list[str] = field(default_factory=list)
    owner: str | None = None

@dataclass
class Credentials:
    platform: str
    api_key: str | None = None
    token: str | None = None
    expires_at: datetime | None = None
    scopes: list[str] = field(default_factory=list)

@dataclass
class RegistrationResult:
    credentials: Credentials
    verification_steps: list[VerificationStep]
    claim_url: str | None = None
```

### 6.3 API Design (Python)

```python
from agentauth import AgentAuth
from agentauth.adapters.moltbook import MoltbookAdapter

# Initialize — loads master key from ~/.config/agentauth/keys.json
auth = AgentAuth(
    adapters=[MoltbookAdapter()],
    store="~/.config/agentauth/credentials.json"
)

# Register — fully autonomous
result = await auth.register("moltbook", name="researcher_bot", description="AI research agent")

# Authenticate
session = await auth.login("moltbook", "researcher_bot")

# Use — pre-authenticated httpx client, drop into any project
async with session.client() as client:
    response = await client.post("/posts", json={"title": "Hello agents!"})

# Multi-agent — one owner, many agents
await auth.register("moltbook", name="writer_bot")
await auth.register("moltbook", name="monitor_bot")
agents = auth.list_agents()
```

### 6.4 Pluggable HTTP Client

The library does **not own the HTTP layer** — it wraps whatever the project already uses:

```python
# Pre-authenticated httpx client (recommended)
async with session.client() as client:
    await client.get("/agents/me")

# Inject into an existing httpx client
async with session.wrap(existing_client) as client:
    await client.post("/posts", json={...})

# Get headers only — integrate with any HTTP library
headers = session.auth_headers()
# → {"Authorization": "Bearer moltbook_xxxxxxxxxxxx"}
requests.get(url, headers=headers)
```

---

## 7. Decisions (Resolved)

### 7.1 Registry Model — Shared Neutral Registry

The AgentAuth registry is a centralized service that all platforms query. Start centralized, document the protocol as an open standard, federate later (see `vision.md`).

### 7.2 Identity Model — Flat (v0.1)

After exploring the master key + derived agent key approach, we simplified v0.1 to a **flat identity model** like Moltbook:

- Agent registers with `name` + optional `description`
- Registry returns an `api_key` (shown once, `agentauth_` prefix)
- Agent authenticates with `Authorization: Bearer agentauth_...`
- No master keys, no crypto derivation, no human claim step

**Why:** The master key model adds complexity that isn't needed when starting a new ecosystem. Agents should be able to register with a single `curl` command. The master key approach is preserved for potential future use (backed up in `agentauth2/`).

### 7.3 Agent Naming — Globally Unique

Agent names are globally unique across the entire registry. The agent name is the primary identifier. Rules: 2-32 characters, starts with lowercase letter, lowercase + numbers + underscores only.

### 7.4 curl-First Design

The primary interface is `curl`. No package installation required for registration and authentication. The Python SDK is optional. The registry serves a skill page at `/` and `/skill.md` with curl-first instructions.

### 7.5 Moltbook Adapter — Deferred

Not in v0.1 scope. The first platform to integrate will be a custom app built by the project owner.

### Open Questions (Deferred)

- Spam prevention strategy (rate limiting at application level)
- Agent lifespan and ownership transfer
- Offline verification (embedded certificates)
- Federation protocol specification
- When/if to introduce master key model for agent fleets

---

## 8. v0.1 Implementation (Actual)

### 8.1 Architecture

```
agentauth/
├── sdk/                          # Python SDK (pip install agentauth)
│   ├── agentauth/
│   │   ├── client.py             # AgentAuth main class
│   │   └── cli.py                # CLI commands (click)
│   └── tests/
├── registry/                     # FastAPI registry service
│   ├── app/
│   │   ├── main.py               # API endpoints
│   │   ├── auth.py               # Bearer token auth
│   │   ├── models.py             # Pydantic request/response models
│   │   ├── store.py              # In-memory store (database is future)
│   │   └── skill.py              # Markdown instruction page
│   └── tests/
└── docs/
```

### 8.2 API Endpoints

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| `POST` | `/v1/agents/register` | None | Register a new agent |
| `GET` | `/v1/agents/me` | Bearer | Get your own profile |
| `GET` | `/v1/agents/{name}` | None | Look up any agent (public) |
| `GET` | `/v1/agents` | None | List all agents (public) |
| `DELETE` | `/v1/agents/{name}` | Bearer | Revoke your agent |

### 8.3 Python SDK

```python
from agentauth import AgentAuth

auth = AgentAuth(registry_url="http://localhost:8000")

# Register — returns dict with api_key
result = auth.register("my_bot", description="What I do")

# Auth headers for any HTTP client
headers = auth.auth_headers("my_bot")
# → {"Authorization": "Bearer agentauth_..."}

# Fetch own profile
me = auth.get_me("my_bot")

# List locally registered agents
agents = auth.list_agents()

# Revoke
auth.revoke("my_bot")
```

### 8.4 CLI

```bash
agentauth register my_bot -d "What I do"
agentauth list
agentauth me my_bot
agentauth revoke my_bot
```

### 8.5 Dependencies

| Dependency | Purpose |
|---|---|
| `httpx` | HTTP client for SDK |
| `click` | CLI interface |
| `fastapi` | Registry API framework |
| `pydantic` | Data models (registry) |

### 8.6 Tests

- Registry: 18 tests (registration, lookup, list, auth, revocation, skill page)
- SDK: 13 tests (credential storage, register, auth headers, revoke)

### Out of scope for v0.1

- Persistent database (in-memory only)
- Rate limiting
- Email-linked / domain-linked tiers
- Moltbook adapter
- Federation / open protocol spec
- TypeScript SDK
- MCP server
