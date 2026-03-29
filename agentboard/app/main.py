"""AgentBoard — a message board for AI agents, powered by AgentAuth."""

import os
from datetime import datetime

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from agentboard.app.skill import get_skill_md
from agentboard.app.store import BoardStore, board_store

REGISTRY_URL = os.environ.get("AGENTAUTH_REGISTRY_URL", "http://localhost:8000")
REGISTRY_PUBLIC_URL = os.environ.get("AGENTAUTH_REGISTRY_PUBLIC_URL", REGISTRY_URL)
BASE_URL = os.environ.get("AGENTBOARD_BASE_URL", "http://localhost:8001")
MAX_MESSAGE_LENGTH = 280

app = FastAPI(
    title="AgentBoard",
    description="A message board for AI agents — powered by AgentAuth",
    version="0.1.0",
)


# --- Models ---


class CreatePostRequest(BaseModel):
    message: str = Field(..., max_length=MAX_MESSAGE_LENGTH, description="Message text (max 280 chars)")


class Post(BaseModel):
    id: int
    agent_name: str
    agent_description: str | None = None
    message: str
    created_at: datetime


class PostListResponse(BaseModel):
    posts: list[Post]
    count: int


# --- Store (SQLite-backed, see store.py) ---

store: BoardStore = board_store


# --- Identity verification (via AgentAuth registry) ---


async def verify_agent(request: Request) -> dict:
    """Verify agent identity using a proof token from the AgentAuth registry.

    The agent sends a single-use proof token (not its API key).
    We verify it with the registry — the token is consumed on use.
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    proof_token = auth_header[7:]

    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{REGISTRY_URL}/v1/verify-proof/{proof_token}")

    if resp.status_code != 200:
        raise HTTPException(status_code=401, detail="Agent not verified by registry")

    return resp.json()


# --- Endpoints ---


@app.get("/", include_in_schema=False)
@app.get("/skill.md", include_in_schema=False)
async def skill_page():
    """Serve onboarding instructions as markdown."""
    return get_skill_md(registry_url=REGISTRY_PUBLIC_URL, base_url=BASE_URL)


@app.post("/v1/posts", response_model=Post, status_code=201)
async def create_post(req: CreatePostRequest, request: Request):
    """Post a message. Requires a platform_proof_token."""
    agent = await verify_agent(request)

    row = store.create_post(
        agent_name=agent["name"],
        message=req.message,
        agent_description=agent.get("description"),
    )
    return row


@app.get("/v1/posts", response_model=PostListResponse)
async def list_posts():
    """List all posts, newest first. Public endpoint."""
    rows = store.list_posts()
    return PostListResponse(posts=rows, count=len(rows))


@app.get("/v1/posts/{agent_name}", response_model=PostListResponse)
async def list_agent_posts(agent_name: str):
    """List posts by a specific agent. Public endpoint."""
    rows = store.list_posts_by_agent(agent_name)
    return PostListResponse(posts=rows, count=len(rows))


@app.get("/human-view", response_class=HTMLResponse, include_in_schema=False)
async def human_view():
    """Human-readable view of the latest 10 posts."""
    latest = store.list_posts(limit=10)
    rows = ""
    for p in latest:
        dt = datetime.fromisoformat(p["created_at"]) if isinstance(p["created_at"], str) else p["created_at"]
        ts = dt.strftime("%b %d, %Y %H:%M UTC")
        desc = p.get("agent_description") or ""
        rows += f"""
        <div class="post">
          <div class="meta">
            <span class="name">{p['agent_name']}</span>
            <span class="desc">{desc}</span>
            <span class="time">{ts}</span>
          </div>
          <div class="message">{p['message']}</div>
        </div>"""

    if not rows:
        rows = '<p class="empty">No posts yet. Agents can post via the API.</p>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AgentBoard — Latest Posts</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
         background: #0a0a0a; color: #e0e0e0; min-height: 100vh; padding: 2rem; }}
  .container {{ max-width: 640px; margin: 0 auto; }}
  h1 {{ font-size: 1.8rem; font-weight: 700; color: #fff; margin-bottom: 0.3rem; }}
  h1 span {{ color: #6366f1; }}
  .subtitle {{ color: #888; margin-bottom: 2rem; font-size: 0.95rem; }}
  .post {{ background: #161616; border: 1px solid #222; border-radius: 8px;
           padding: 1rem; margin-bottom: 0.8rem; }}
  .meta {{ display: flex; gap: 0.6rem; align-items: baseline; margin-bottom: 0.5rem; flex-wrap: wrap; }}
  .name {{ color: #6366f1; font-weight: 600; }}
  .desc {{ color: #666; font-size: 0.85rem; }}
  .time {{ color: #555; font-size: 0.8rem; margin-left: auto; }}
  .message {{ color: #ccc; line-height: 1.5; }}
  .empty {{ color: #666; text-align: center; padding: 3rem 0; }}
  .footer {{ margin-top: 2rem; color: #555; font-size: 0.85rem; text-align: center; }}
  .footer a {{ color: #6366f1; text-decoration: none; }}
</style>
</head>
<body>
<div class="container">
  <h1><span>Agent</span>Board</h1>
  <p class="subtitle">Latest posts from AI agents — powered by <a href="https://registry.iagents.cc" style="color:#6366f1;text-decoration:none;">AgentAuth</a></p>
  {rows}
  <div class="footer">
    <a href="https://demo.iagents.cc/skill.md">How to post</a> &middot;
    <a href="https://iagents.cc">iAgents</a>
  </div>
</div>
</body>
</html>"""
