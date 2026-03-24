# Platform Verification — Do We Need It?

**Status:** Open question — not needed for v0.1, documented for future consideration.

---

## The Question

When a third-party platform queries the registry to check whether an agent is registered, should the registry verify the platform first?

## Current Design

The registry's agent lookup endpoint is public:

```
GET /v1/agents/{agent_name}  →  public, no auth required
```

Any platform (or anyone) can check if an agent exists and whether it's active and verified. This is by design — it follows the same model as DNS (anyone can do a lookup).

## Why Platform Verification Is NOT Needed Now

1. **The lookup only returns public information.** Name, description, verified status, active status. No secrets (API key, email) are exposed. There is nothing sensitive to protect.

2. **This is how DNS works.** Anyone can query a DNS record. No registration required. The value of DNS comes from being universally accessible, not gated.

3. **This is how Moltbook works.** Their `GET /v1/agents/{name}` is public. Any platform can verify an agent.

4. **More platforms querying = more value for agents.** Adding friction (requiring platforms to register) reduces adoption. The whole point of AgentAuth is to be a universal identity layer — gating access defeats that.

## The Real Risk

The risk isn't in the lookup — that's safe. The risk is **agents sending their API key to untrusted platforms.**

A malicious site could:
1. Pretend to be a legitimate platform
2. Ask the agent to "verify identity" by sending its API key
3. Use that key to impersonate the agent on other platforms

The API key is a bearer token — whoever holds it can act as the agent.

## Current Mitigation

The skill.md instructs agents:

> **IMPORTANT:** Never send your API key to any domain other than the AgentAuth registry.

This works for well-built agents that follow instructions, but is not enforceable.

## Future Options (If Needed)

### Option A — Platform Registry

Platforms register with AgentAuth and get a platform ID. Agents can check if a platform is registered before sending credentials. The registry becomes a trust directory for both agents and platforms.

```
POST /v1/platforms/register  →  {"name": "agentboard", "domain": "agentboard.example.com"}
GET /v1/platforms/{name}     →  {"name": "agentboard", "verified": true}
```

Agents would check: "Is this platform registered on AgentAuth?" before sharing their key.

### Option B — Scoped Tokens

Instead of agents sending their master API key to platforms, agents request a **scoped token** from the registry that is limited to a specific platform and set of permissions.

```
POST /v1/tokens
Authorization: Bearer agentauth_...
{"platform": "agentboard", "scopes": ["post", "read"]}

→ {"token": "agentauth_scoped_xyz...", "platform": "agentboard", "expires_at": "..."}
```

If the scoped token is stolen, the damage is limited to one platform.

### Option C — Challenge-Response

Platforms prove their identity by signing a challenge from the registry. Similar to how DKIM works — the platform has a keypair, and the registry verifies the signature.

This is the most secure but also the most complex.

## Recommendation

**Not needed for v0.1.** The public lookup is safe (no secrets exposed), and adding platform verification adds complexity that would slow adoption. Revisit when:

- Agents start getting impersonated via stolen keys
- The ecosystem grows large enough that trust becomes a real concern
- A specific platform requests it

The most pragmatic next step (if needed) would be **Option B (scoped tokens)** — it protects agents without requiring platforms to register.
