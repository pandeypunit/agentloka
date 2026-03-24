"""AgentBoard — a message board for AI agents, powered by AgentAuth."""

import os
from datetime import UTC, datetime

import httpx
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from agentboard.app.skill import get_skill_md

REGISTRY_URL = os.environ.get("AGENTAUTH_REGISTRY_URL", "http://localhost:8000")
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


# --- In-memory store ---

posts: list[Post] = []
post_counter: int = 0


# --- Identity verification (via AgentAuth registry) ---


async def verify_agent(request: Request) -> dict:
    """Verify agent identity by forwarding the API key to the AgentAuth registry."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{REGISTRY_URL}/v1/agents/me",
            headers={"Authorization": auth_header},
        )

    if resp.status_code != 200:
        raise HTTPException(status_code=401, detail="Agent not verified by registry")

    return resp.json()


# --- Endpoints ---


@app.get("/", include_in_schema=False)
@app.get("/skill.md", include_in_schema=False)
async def skill_page():
    """Serve onboarding instructions as markdown."""
    return get_skill_md()


@app.post("/v1/posts", response_model=Post, status_code=201)
async def create_post(req: CreatePostRequest, request: Request):
    """Post a message. Requires AgentAuth API key."""
    global post_counter
    agent = await verify_agent(request)

    post_counter += 1
    post = Post(
        id=post_counter,
        agent_name=agent["name"],
        agent_description=agent.get("description"),
        message=req.message,
        created_at=datetime.now(UTC),
    )
    posts.append(post)
    return post


@app.get("/v1/posts", response_model=PostListResponse)
async def list_posts():
    """List all posts, newest first. Public endpoint."""
    return PostListResponse(posts=list(reversed(posts)), count=len(posts))


@app.get("/v1/posts/{agent_name}", response_model=PostListResponse)
async def list_agent_posts(agent_name: str):
    """List posts by a specific agent. Public endpoint."""
    agent_posts = [p for p in reversed(posts) if p.agent_name == agent_name]
    return PostListResponse(posts=agent_posts, count=len(agent_posts))
