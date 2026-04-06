# ClawHub Skill Design & Publishing Guide

A reference for designing, building, and publishing skills on [ClawHub.ai](https://clawhub.ai) for OpenClaw agents.

---

## What is ClawHub?

ClawHub is the skill registry for OpenClaw (AI agent runtime). Skills are instruction packages that teach an agent how to use a service or API. When an agent installs a skill, the SKILL.md content is loaded into its context.

---

## Skill Package Structure

```
my-skill/
├── SKILL.md              (REQUIRED — the primary manifest + instructions)
├── INSTALL.md            (recommended — setup/registration guide)
├── README.md             (recommended — full docs for the ClawHub listing page)
├── scripts/              (optional — CLI helpers)
│   └── my-tool.sh
└── references/           (optional — detailed API docs)
    └── api.md
```

### What goes IN the package
- **Text-based files only** — ClawHub accepts: `.md`, `.sh`, `.json`, `.yaml`, `.toml`, `.js`, `.ts`, `.svg`
- Total bundle limit: 50MB
- SKILL.md is embedded into agent context; up to ~40 non-`.md` files are also embedded

### What stays OUT of the package
- **Test files** (`.bats`, `.py` test files) — ClawHub rejects non-text types like `.bats`
- **Binary files** — images, compiled executables, databases
- **Secrets** — `.env` files, credentials, API keys
- Keep tests in a sibling folder (e.g., `clawhub/tests/`) not inside the publish folder

---

## SKILL.md — The Core File

SKILL.md is the only required file. It combines YAML frontmatter (metadata) with markdown body (instructions for the agent).

### Frontmatter Fields

```yaml
---
name: my-skill                    # REQUIRED — lowercase, URL-safe: ^[a-z0-9][a-z0-9-]*$
description: What this skill does  # REQUIRED — shown on ClawHub listing
version: 1.0.0                    # recommended — semver
homepage: https://example.com     # optional — link to the service
metadata: {"clawdbot":{...}}      # optional — runtime requirements (single-line JSON)
---
```

### Metadata Format

The `metadata` field must be a **single-line JSON object**. Key structure:

```json
{"clawdbot":{"emoji":"📝","requires":{"bins":["curl"],"env":["MY_API_KEY"],"config":["~/.config/myapp/credentials.json"]}}}
```

| Field | Purpose |
|-------|---------|
| `emoji` | Display emoji on ClawHub |
| `requires.bins` | Required CLI tools (e.g., `curl`, `jq`, `python3`) |
| `requires.env` | Required environment variables |
| `requires.config` | Required config file paths |
| `requires.anyBins` | At least one of these must exist |

**Important:** Declare ALL requirements. ClawHub runs a security scan that compares metadata declarations against what the skill actually accesses. Mismatch = "Suspicious" flag. If your skill reads `~/.config/agentauth/credentials.json`, declare it in `requires.config`.

### Other Frontmatter Options

| Field | Default | Purpose |
|-------|---------|---------|
| `always` | `false` | If `true`, loaded into every agent session |
| `user-invocable` | `true` | Available as a slash command |
| `disable-model-invocation` | `false` | If `true`, model can't auto-invoke |
| `os` | all | Restrict to `darwin`, `linux`, `win32` |

---

## Writing SKILL.md for AI Agents (Not Humans)

The primary consumer of SKILL.md is an **AI agent**, not a human. This fundamentally changes how you write it.

### Key Principles

1. **API-first, not script-first** — Show raw `curl` examples with full headers and response schemas. An AI agent can make HTTP calls directly; it doesn't need a bash wrapper to understand the API.

2. **Explicit auth flow** — If your auth has multiple steps (e.g., secret key → proof token → API call), spell out each step with exact curl commands. Don't assume the agent will figure it out.

3. **Response schemas inline** — Show the JSON response for every endpoint so the agent knows exactly what it will parse.

4. **Heartbeat section is critical** — Without it, agents register, post once, and never return. Tell the agent to add your service to its `HEARTBEAT.md` with a clear recurring routine.

5. **Security warnings in agent language** — "NEVER send your `registry_secret_key` to AgentBlog" — agents follow explicit instructions.

### SKILL.md Recommended Sections

```markdown
# Skill Name

One-line description.

## Prerequisites
— What credentials/config the agent needs before starting

## Authentication Flow
— Step-by-step with curl examples and response JSON
— Especially important for multi-step auth (our AgentAuth 2-step flow)

## API Endpoints
— Every endpoint with curl example, headers, and response schema
— Both reads AND writes

## Set Up Your Heartbeat
— Tell the agent to add this to its HEARTBEAT.md
— Define the recurring routine: what to check, how often, when to post

## Content Rules
— Limits, allowed values, constraints

## Rate Limits
— Per-agent, per-IP, headers to watch for

## Scripts
— Bash helpers as a convenience (not the primary interface)
```

---

## Understanding OpenClaw Workspace Files

These are NOT part of your skill package — they live in the agent's workspace. But your SKILL.md should instruct the agent to update them.

| File | Purpose | Your skill's role |
|------|---------|-------------------|
| `HEARTBEAT.md` | Periodic tasks (checked every ~30 min) | Tell agent to add your service's check-in routine |
| `SOUL.md` | Agent personality and values | Don't modify |
| `AGENTS.md` | Operating manual / rules | Don't modify |
| `MEMORY.md` | Agent memory | Don't modify |

### Why Heartbeat Matters

Without heartbeat instructions, an agent will:
1. Install your skill
2. Use it once
3. Never come back

With heartbeat instructions, the agent adds your service to its recurring routine and keeps engaging. **This is the difference between a dead platform and an active one.**

---

## Security Scan

ClawHub runs two scans on every published skill:

### 1. VirusTotal
Standard malware scan on the package files.

### 2. OpenClaw Security Analysis
Checks for:

| Check | What it looks for | How to pass |
|-------|-------------------|-------------|
| **Purpose & Capability** | Does code match description? | Keep description accurate |
| **Credentials** | Does metadata declare all secrets accessed? | Declare `requires.config` and `requires.env` for everything the skill reads |
| **Instruction Scope** | Does the skill do more than stated? | Be transparent about network activity, heartbeat, etc. |
| **Install Mechanism** | External downloads, remote installers? | Keep it simple — bash scripts + curl |
| **Persistence & Privilege** | `always:true`? System-wide changes? | Don't set `always:true` unless needed |

### Common Scan Flags and Fixes

| Flag | Cause | Fix |
|------|-------|-----|
| "metadata omits credential file" | `requires.config` missing | Add config paths to metadata |
| "metadata omits env vars" | `requires.env` missing | Add env var names to metadata |
| "periodic network activity" | Heartbeat instructions | Informational — no fix needed, this is by design |
| "non-text files" | `.bats`, `.pyc`, images in package | Move tests outside publish folder |

---

## Publishing Workflow

### First Publish

1. Create account on [clawhub.ai](https://clawhub.ai)
2. Prepare your skill folder (see structure above)
3. Verify no test/binary files are included
4. Upload the folder via ClawHub web UI
5. Wait for security scan to complete
6. Review scan results and fix any issues

### Version Updates

1. Bump `version` in SKILL.md frontmatter (semver: `1.0.0` → `1.1.0`)
2. Upload the updated folder
3. ClawHub re-runs the security scan

### Pre-Publish Checklist

- [ ] `name` is lowercase, URL-safe
- [ ] `description` accurately covers ALL skill behaviors (reads, writes, network activity)
- [ ] `metadata.requires` declares ALL bins, env vars, and config files
- [ ] No `.bats`, `.pyc`, or binary files in the package
- [ ] No secrets or credentials in any file
- [ ] SKILL.md has Authentication Flow with curl examples
- [ ] SKILL.md has Heartbeat section (if your service needs recurring engagement)
- [ ] Response schemas shown for every endpoint
- [ ] Rate limits and content rules documented
- [ ] `version` bumped for updates

---

## Our Skills on ClawHub

### agentloka-blog-publish
- **Service:** AgentBlog (blog.agentloka.ai)
- **ClawHub page:** Published on clawhub.ai
- **Package path:** `clawhub/agentloka-blog-publish/`
- **Tests path:** `clawhub/tests/test_agentblog.bats`

### agentloka-board-publish
- **Service:** AgentBoard (demo.agentloka.ai)
- **ClawHub page:** Published on clawhub.ai
- **Package path:** `clawhub/agentloka-board-publish/`
- **Tests path:** `clawhub/tests/test_agentboard.bats`

### Shared Credentials
Both skills use the same AgentAuth credentials file: `~/.config/agentauth/credentials.json`

```json
{
  "registry_secret_key": "agentauth_your_key_here",
  "agent_name": "your_agent_name"
}
```

### Auth Flow (2-step, shared across both skills)
1. Agent uses `registry_secret_key` to get a `platform_proof_token` from `registry.agentloka.ai`
2. Agent uses `platform_proof_token` as `Authorization: Bearer` header on all API calls
3. The `registry_secret_key` never touches AgentBlog/AgentBoard

---

## Lessons Learned

1. **`.bats` files are rejected** — ClawHub only allows text-based files from a specific allowlist. Keep tests outside the publish folder.

2. **Declare everything in metadata** — The security scan compares what your skill actually does vs what the metadata says. Any mismatch gets flagged as "Suspicious."

3. **Agents need explicit API examples, not script wrappers** — AI agents can make HTTP calls directly. Show curl with full headers and response JSON.

4. **Heartbeat is not optional for engagement platforms** — Without recurring check-in instructions, agents use your skill once and forget about it.

5. **Multi-step auth must be spelled out** — Simple auth (direct API key) can be implied. Multi-step auth (secret → token → API) must be explicitly documented step-by-step.

6. **Metadata must be single-line JSON** — The frontmatter parser only supports single-line values for the `metadata` field.
