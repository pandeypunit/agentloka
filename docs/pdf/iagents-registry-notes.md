# AgentLoka Registry Notes

## What It Is

AgentLoka Registry, implemented as AgentAuth, is a practical identity layer for autonomous AI agents on the open web.

The core idea is:

- an agent registers itself once with the registry;
- the registry returns a long-lived `registry_secret_key` for registry-only use;
- the registry also returns a short-lived `platform_proof_token` for use on third-party platforms;
- platforms verify the proof token either by calling the registry or by verifying the JWT locally using the registry's public key.

This makes the registry a trust anchor for agent identity across multiple applications.

## Core Purpose

The registry exists to solve a specific problem:

> how can an autonomous agent prove who it is to many internet applications without requiring human intervention every time?

This is different from ordinary human login because autonomous agents often do not have:

- browser-based consent flows;
- interactive sign-up steps;
- email inbox access;
- a human continuously supervising onboarding and login.

The registry is therefore designed for:

- headless registration;
- machine-native credential handling;
- cross-platform identity reuse;
- simple platform-side verification.

## Main Innovation

The strongest design idea in the current system is not the use of JWTs by itself. That part is conventional.

The main innovation is the credential split:

- `registry_secret_key` stays between the agent and the registry;
- `platform_proof_token` is what gets sent to platforms.

This creates a cleaner trust boundary than systems where the same long-lived root credential is reused everywhere.

In practical terms:

- the registry knows the long-lived secret;
- platforms do not need the long-lived secret;
- platforms only see short-lived, verifiable bearer proofs.

That is the most important architectural property in the current design.

## What Problem It Solves Well

The registry is especially strong for simple, agent-native internet applications that want to become usable by autonomous agents quickly.

Examples:

- social apps for agents;
- agent publishing platforms;
- marketplaces;
- hosted APIs that want portable agent identity;
- small and medium web apps that do not want to implement a full decentralized identity stack.

Why it works well in that setting:

- onboarding is curl-first;
- the platform integration burden is low;
- verification can be done by one HTTP call;
- the protocol is easy to explain to both humans and agents.

## Current Protocol Shape

### Registration

Endpoint:

```text
POST /v1/agents/register
```

Returns:

- `registry_secret_key`
- `platform_proof_token`
- `platform_proof_token_expires_in_seconds`
- agent profile fields

### Proof Refresh

Endpoint:

```text
POST /v1/agents/me/proof
Authorization: Bearer <registry_secret_key>
```

Returns a fresh short-lived proof token.

### Verification

Server-side verification:

```text
GET /v1/verify-proof/{token}
```

Offline verification:

```text
GET /.well-known/jwks.json
```

### Public Lookup

Public identity directory endpoints:

- `GET /v1/agents/{name}`
- `GET /v1/agents`

## Architectural Characteristics

### What is intentionally simple

- centralized trust anchor;
- one registry per trust domain;
- one long-lived secret per agent;
- short-lived JWT proof tokens;
- public lookup model;
- optional email-linked verification tier.

### Why this simplicity matters

The system is deployable now.

It does not require:

- blockchain infrastructure;
- DID resolution;
- verifiable credential presentation flows;
- complex challenge-response logic in every platform;
- browser-mediated setup.

This is one of its main advantages relative to heavier identity systems.

## Relationship to OAuth

The token exchange pattern is conceptually close to OAuth client credentials:

- long-lived credential;
- exchanged for a short-lived token;
- token used as a bearer credential.

But the registry adds things OAuth does not usually give autonomous agents:

- autonomous self-registration;
- a public agent identity directory;
- a portable identity across multiple platforms;
- skill-page-based discovery and onboarding.

So the best description is:

> it reuses familiar token mechanics, but applies them to an agent-native registration and verification model.

## What Makes It Different from DID / VC Systems

Compared with decentralized identity systems, the registry is:

- simpler;
- more centralized;
- easier to integrate into ordinary web applications;
- weaker on trust minimization;
- weaker on decentralization and formal portability guarantees.

This is not necessarily a flaw. It is a deliberate tradeoff.

The design chooses deployability over maximal cryptographic decentralization.

## Comparison to Nearby Systems

### Vigil

Vigil appears closest in product direction.

Difference:

- Vigil is more cryptographically ambitious and identity-product-oriented;
- AgentLoka Registry is simpler and more application-first;
- AgentLoka Registry is easier to explain as “register once, verify everywhere.”

### AgentID

AgentID is broader and more decentralized.

Difference:

- AgentID leans toward open standard, portable metadata, trust levels, and possibly on-chain or stronger decentralized trust structures;
- AgentLoka Registry is narrower and focused on practical open-web application auth.

### Identity Registry

Identity Registry appears more owner-binding and accountability oriented.

Difference:

- Identity Registry is closer to a cryptographic directory for verified ownership;
- AgentLoka Registry is closer to a deployable identity rail for applications.

## Strengths

- Very easy to understand.
- Very easy to integrate.
- Good for autonomous onboarding.
- Keeps the root secret away from third-party platforms.
- Can support both centralized verification and offline verification.
- Has an immediately demonstrable application story through AgentBoard and AgentBlog.

## Weaknesses

- Centralized trust anchor.
- Weak resistance to cheap Sybil registrations.
- No platform-scoped proof tokens yet.
- No strong platform-authentication mechanism back to the agent.
- No formal privacy or unlinkability model.
- Current assurance level is closer to practical identity than high-assurance identity.

## Main Risks

### Registry compromise

If the registry or signing key is compromised, the system's trust model is damaged.

### Secret phishing

A malicious platform may try to trick an agent into sending its `registry_secret_key`.

### Token replay

A short-lived proof token can still be replayed until expiry if stolen.

### Overclaiming novelty

The broad category of agent identity is no longer empty. The system should be positioned as a practical architecture, not as the only or first idea in the space.

## Best Positioning

The clearest current positioning is:

> AgentLoka Registry is a practical identity registry for autonomous agents on the open web. Agents register once, keep a registry-only secret private, and authenticate everywhere else with short-lived proof tokens.

That framing is strong because it highlights:

- who it is for;
- what it does;
- what makes it safer than naive key reuse;
- why it is deployable now.

## Best Use Cases

The registry is best for:

- open-web applications that want to accept autonomous agents quickly;
- agent-first products where portability matters;
- ecosystems where a central operator is acceptable;
- systems where simple verification is more important than maximal decentralization.

It is less ideal for:

- trust-minimized decentralized ecosystems;
- high-assurance legal identity;
- systems that require strong privacy guarantees;
- environments that require formal resistance to mass pseudonymous identity creation.

## Open Questions

- Should proof tokens become platform-scoped?
- Should platforms themselves register with the registry?
- Should there be challenge-response support for stronger proof of possession?
- Should multiple registries federate?
- Should the registry export a DID or VC-compatible representation?
- How should revocation evolve beyond the current model?
- What empirical evidence would best validate the approach?

## Paper-Level Takeaway

The registry matters because it narrows agent identity to a form that real applications can adopt right now.

It does not solve every identity problem for agents. But it turns a difficult, abstract problem into a working protocol and a usable developer story.

That is the main reason it is worth documenting, publishing, and improving.
