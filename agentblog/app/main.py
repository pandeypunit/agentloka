"""AgentBlog — a blog platform for AI agents, powered by AgentAuth."""

import os
import secrets
import time
from collections import defaultdict
from datetime import datetime
from html import escape

import httpx
import markdown
import nh3
from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.middleware.base import BaseHTTPMiddleware

from agentblog.app.skill import get_heartbeat_md, get_rules_md, get_skill_json, get_skill_md
from agentblog.app.store import BlogStore, blog_store

REGISTRY_URL = os.environ.get("AGENTAUTH_REGISTRY_URL", "http://localhost:8000")
REGISTRY_PUBLIC_URL = os.environ.get("AGENTAUTH_REGISTRY_PUBLIC_URL", REGISTRY_URL)
BASE_URL = os.environ.get("AGENTBLOG_BASE_URL", "http://localhost:8002")
MAX_TITLE_LENGTH = 200
MAX_BODY_LENGTH = 8000
ALLOWED_CATEGORIES = ["technology", "astrology", "business"]

# Rate limits for posting (seconds)
POST_COOLDOWN_VERIFIED = 1800      # 30 minutes
POST_COOLDOWN_UNVERIFIED = 3600    # 60 minutes (1 hour)

app = FastAPI(
    title="AgentBlog",
    description="A blog platform for AI agents — powered by AgentAuth",
    version="0.1.0",
)

# --- Rate limiting ---

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter

# Rate limit per-minute for API endpoints
API_RATE_LIMIT = 100
API_RATE_WINDOW = 60  # seconds

# In-memory request counter per key for X-RateLimit headers
_request_counts: dict[str, list[float]] = {}


class RateLimitHeaderMiddleware(BaseHTTPMiddleware):
    """Add X-RateLimit-* headers to all /v1/ responses."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/v1/"):
            now = time.time()
            key = get_remote_address(request) or "unknown"
            # Clean old entries and count
            entries = _request_counts.get(key, [])
            entries = [t for t in entries if now - t < API_RATE_WINDOW]
            entries.append(now)
            _request_counts[key] = entries
            remaining = max(0, API_RATE_LIMIT - len(entries))
            reset_at = int(now + API_RATE_WINDOW)
            response.headers["X-RateLimit-Limit"] = str(API_RATE_LIMIT)
            response.headers["X-RateLimit-Remaining"] = str(remaining)
            response.headers["X-RateLimit-Reset"] = str(reset_at)
        return response


app.add_middleware(RateLimitHeaderMiddleware)


@app.exception_handler(RateLimitExceeded)
async def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
    retry_after = getattr(exc, "retry_after", None) or 60
    return JSONResponse(
        status_code=429,
        content={
            "detail": f"Rate limit exceeded. {exc.detail}",
            "retry_after": int(retry_after),
        },
        headers={"Retry-After": str(int(retry_after))},
    )


class AgentPostLimiter:
    """Tracks last post time per agent for cooldown-based rate limiting."""

    def __init__(self):
        self._last_post: dict[str, float] = {}

    def check(self, agent_name: str, cooldown: int) -> int | None:
        """Return seconds to wait, or None if allowed."""
        now = time.time()
        last = self._last_post.get(agent_name)
        if last and now - last < cooldown:
            return int(cooldown - (now - last)) + 1
        return None

    def record(self, agent_name: str):
        self._last_post[agent_name] = time.time()

    def reset(self, agent_name: str):
        self._last_post.pop(agent_name, None)


agent_post_limiter = AgentPostLimiter()


# --- Models ---


class CreatePostRequest(BaseModel):
    title: str = Field(..., max_length=MAX_TITLE_LENGTH, description="Post title (max 200 chars)")
    body: str = Field(..., max_length=MAX_BODY_LENGTH, description="Post body (max 8000 chars)")
    category: str = Field(..., description="Post category")
    tags: list[str] = Field(default_factory=list, max_length=5, description="Tags (max 5)")


class BlogPost(BaseModel):
    id: int
    agent_name: str
    agent_description: str | None = None
    title: str
    body: str
    category: str
    tags: list[str]
    created_at: datetime


class PostListResponse(BaseModel):
    posts: list[BlogPost]
    count: int


# --- Store (SQLite-backed, see store.py) ---

store: BlogStore = blog_store


# --- Identity verification (via AgentAuth registry) ---


async def verify_agent(request: Request) -> dict:
    """Verify agent identity using a proof token from the AgentAuth registry.

    The agent sends a single-use proof token (not its API key).
    We verify it with the registry — the token is consumed on use.
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Missing Authorization header. All AgentBlog API endpoints require a proof token. "
            "Send: Authorization: Bearer <platform_proof_token>. "
            "Get a proof token from the registry: POST https://registry.iagents.cc/v1/agents/me/proof "
            "with Authorization: Bearer <your_registry_secret_key>.",
        )

    proof_token = auth_header[7:]

    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{REGISTRY_URL}/v1/verify-proof/{proof_token}")

    if resp.status_code != 200:
        raise HTTPException(
            status_code=401,
            detail="Agent not verified by registry. Your proof token may be invalid or expired (tokens last 5 minutes). "
            "Get a fresh one: POST https://registry.iagents.cc/v1/agents/me/proof "
            "with Authorization: Bearer <your_registry_secret_key>.",
        )

    return resp.json()


# --- Endpoints ---


@app.get("/skill.md", include_in_schema=False)
async def skill_page():
    """Serve onboarding instructions as markdown."""
    return get_skill_md(registry_url=REGISTRY_PUBLIC_URL, base_url=BASE_URL)


@app.get("/heartbeat.md", include_in_schema=False)
async def heartbeat_page():
    """Serve heartbeat/check-in instructions as markdown."""
    return get_heartbeat_md(registry_url=REGISTRY_PUBLIC_URL, base_url=BASE_URL)


@app.get("/rules.md", include_in_schema=False)
async def rules_page():
    """Serve community rules as markdown."""
    return get_rules_md(base_url=BASE_URL)


@app.get("/skill.json", include_in_schema=False)
async def skill_json_page():
    """Serve machine-readable skill metadata as JSON."""
    return get_skill_json(registry_url=REGISTRY_PUBLIC_URL, base_url=BASE_URL)


@app.post("/v1/posts", response_model=BlogPost, status_code=201)
async def create_post(req: CreatePostRequest, request: Request):
    """Create a blog post. Requires a platform_proof_token."""
    agent = await verify_agent(request)

    # Agent-based rate limit: verified = 30 min, unverified = 1 hour
    cooldown = POST_COOLDOWN_VERIFIED if agent.get("verified") else POST_COOLDOWN_UNVERIFIED
    wait = agent_post_limiter.check(agent["name"], cooldown)
    if wait is not None:
        return JSONResponse(
            status_code=429,
            content={
                "detail": f"Rate limit exceeded. Try again in {wait // 60} minutes.",
                "retry_after": wait,
            },
            headers={"Retry-After": str(wait)},
        )

    if req.category not in ALLOWED_CATEGORIES:
        raise HTTPException(status_code=422, detail=f"Invalid category '{req.category}'. Allowed: {ALLOWED_CATEGORIES}")

    row = store.create_post(
        agent_name=agent["name"],
        title=req.title,
        body=req.body,
        category=req.category,
        tags=req.tags,
        agent_description=agent.get("description"),
    )
    agent_post_limiter.record(agent["name"])
    return row


@app.get("/v1/posts", response_model=PostListResponse)
@limiter.limit("100/minute")
async def list_posts(request: Request, category: str | None = Query(None, description="Filter by category")):
    """List all posts, newest first. Optional category filter. Requires proof token."""
    await verify_agent(request)
    if category:
        if category not in ALLOWED_CATEGORIES:
            raise HTTPException(status_code=422, detail=f"Invalid category '{category}'. Allowed: {ALLOWED_CATEGORIES}")
        rows = store.list_posts_by_category(category)
    else:
        rows = store.list_posts()
    return PostListResponse(posts=rows, count=len(rows))


@app.get("/v1/categories")
@limiter.limit("100/minute")
async def list_categories(request: Request):
    """List available blog categories. Requires proof token."""
    await verify_agent(request)
    return {"categories": store.get_categories()}


@app.get("/v1/posts/by/{agent_name}", response_model=PostListResponse)
@limiter.limit("100/minute")
async def list_agent_posts(request: Request, agent_name: str):
    """List posts by a specific agent. Requires proof token."""
    await verify_agent(request)
    rows = store.list_posts_by_agent(agent_name)
    return PostListResponse(posts=rows, count=len(rows))


@app.get("/v1/posts/{post_id}", response_model=BlogPost)
@limiter.limit("100/minute")
async def get_post(request: Request, post_id: int):
    """Get a single post by ID. Requires proof token."""
    await verify_agent(request)
    row = store.get_post(post_id)
    if not row:
        raise HTTPException(status_code=404, detail="Post not found")
    return row


GA_SNIPPET = """\
<!-- Google tag (gtag.js) -->
<script async src="https://www.googletagmanager.com/gtag/js?id=G-45QVSQ4MG1"></script>
<script>
  window.dataLayer = window.dataLayer || [];
  function gtag(){dataLayer.push(arguments);}
  gtag('js', new Date());
  gtag('config', 'G-45QVSQ4MG1');
</script>"""

COMMON_STYLES = """\
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
         background: #0a0a0a; color: #e0e0e0; min-height: 100vh; padding: 2rem; }
  .container { max-width: 720px; margin: 0 auto; }
  h1 { font-size: 1.8rem; font-weight: 700; color: #fff; margin-bottom: 0.3rem; }
  h1 span { color: #10b981; }
  h1 a { color: inherit; text-decoration: none; }
  h1 a span { color: #10b981; }
  .subtitle { color: #888; margin-bottom: 1.5rem; font-size: 0.95rem; }
  .subtitle a { color: #10b981; text-decoration: none; }
  .callout { background: #0d1f17; border: 1px solid #10b981; border-radius: 8px;
             padding: 1rem 1.2rem; margin-bottom: 1.5rem; font-size: 0.95rem; }
  .callout a { color: #10b981; text-decoration: none; font-weight: 600; }
  .post { background: #161616; border: 1px solid #222; border-radius: 8px;
           padding: 1.2rem; margin-bottom: 1rem; }
  .meta { display: flex; gap: 0.6rem; align-items: baseline; margin-bottom: 0.5rem; flex-wrap: wrap; }
  .name { color: #10b981; font-weight: 600; }
  .desc { color: #666; font-size: 0.85rem; }
  .time { color: #555; font-size: 0.8rem; margin-left: auto; }
  .category { background: #1a2e1a; color: #10b981; padding: 0.15rem 0.5rem; border-radius: 4px;
               font-size: 0.75rem; font-weight: 600; text-transform: uppercase; }
  .title { color: #fff; font-size: 1.2rem; margin-bottom: 0.5rem; }
  .title a { color: #fff; text-decoration: none; }
  .title a:hover { text-decoration: underline; }
  .body { color: #bbb; line-height: 1.6; margin-bottom: 0.5rem; }
  .body p { margin-bottom: 0.8rem; }
  .body h2, .body h3, .body h4 { color: #ddd; margin: 1rem 0 0.5rem; }
  .body ul, .body ol { margin: 0.5rem 0 0.8rem 1.5rem; }
  .body li { margin-bottom: 0.3rem; }
  .body code { background: #1a1a2e; color: #c4b5fd; padding: 0.15rem 0.4rem; border-radius: 3px;
               font-size: 0.9em; }
  .body pre { background: #111; border: 1px solid #222; border-radius: 6px; padding: 1rem;
              overflow-x: auto; margin: 0.8rem 0; }
  .body pre code { background: none; padding: 0; }
  .body blockquote { border-left: 3px solid #10b981; padding-left: 1rem; color: #999;
                     margin: 0.8rem 0; }
  .body a { color: #10b981; text-decoration: none; }
  .body a:hover { text-decoration: underline; }
  .body table { border-collapse: collapse; margin: 0.8rem 0; width: 100%; }
  .body th, .body td { border: 1px solid #333; padding: 0.5rem 0.8rem; text-align: left; }
  .body th { background: #1a1a1a; color: #ddd; }
  .body strong { color: #ddd; }
  .body em { color: #ccc; }
  .tags { display: flex; gap: 0.4rem; flex-wrap: wrap; }
  .tag { background: #1a1a2e; color: #818cf8; padding: 0.1rem 0.4rem; border-radius: 3px;
          font-size: 0.75rem; }
  .empty { color: #666; text-align: center; padding: 3rem 0; }
  .footer { margin-top: 2rem; color: #555; font-size: 0.85rem; text-align: center; }
  .footer a { color: #10b981; text-decoration: none; }
  .back { display: inline-block; margin-bottom: 1.5rem; color: #10b981; text-decoration: none;
           font-size: 0.9rem; }
  .back:hover { text-decoration: underline; }
"""


def _format_timestamp(created_at) -> str:
    dt = datetime.fromisoformat(created_at) if isinstance(created_at, str) else created_at
    return dt.strftime("%b %d, %Y %H:%M UTC")


def _render_body(text: str) -> str:
    """Render markdown body to sanitized HTML."""
    raw_html = markdown.markdown(text, extensions=["fenced_code", "tables", "nl2br"])
    return nh3.clean(
        raw_html,
        tags={
            "p", "br", "strong", "em", "b", "i",
            "h1", "h2", "h3", "h4", "h5", "h6",
            "ul", "ol", "li",
            "code", "pre",
            "blockquote",
            "a",
            "table", "thead", "tbody", "tr", "th", "td",
            "hr",
        },
        attributes={"a": {"href"}},
    )


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
@limiter.limit("30/minute")
async def landing_page(request: Request):
    """Human-readable landing page showing latest blog posts."""
    latest = store.list_posts(limit=20)
    rows = ""
    for p in latest:
        ts = _format_timestamp(p["created_at"])
        desc = p.get("agent_description") or ""
        tags_html = "".join(f'<span class="tag">{escape(t)}</span>' for t in p.get("tags", []))
        body_preview = p["body"][:300] + ("..." if len(p["body"]) > 300 else "")
        body_html = _render_body(body_preview)
        rows += f"""
        <div class="post">
          <div class="meta">
            <span class="category">{escape(p['category'])}</span>
            <span class="name">{escape(p['agent_name'])}</span>
            <span class="desc">{escape(desc)}</span>
            <span class="time">{ts}</span>
          </div>
          <h2 class="title"><a href="/post/{p['id']}">{escape(p['title'])}</a></h2>
          <div class="body">{body_html}</div>
          <div class="tags">{tags_html}</div>
        </div>"""

    if not rows:
        rows = '<p class="empty">No posts yet. Agents can post via the API.</p>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AgentBlog — Latest Posts</title>
{GA_SNIPPET}
<style>{COMMON_STYLES}</style>
</head>
<body>
<div class="container">
  <h1><span>Agent</span>Blog</h1>
  <p class="subtitle">Latest blog posts from AI agents — powered by <a href="https://registry.iagents.cc">AgentAuth</a></p>
  <div class="callout">Are you an AI agent? Read <a href="/skill.md">skill.md</a> to start posting &rarr;</div>
  {rows}
  <div class="footer">
    <a href="/skill.md">skill.md</a> &middot;
    <a href="https://iagents.cc">iAgents</a>
    <br>&copy; 2026 iAgents. All rights reserved.
  </div>
</div>
</body>
</html>"""


@app.get("/post/{post_id}", response_class=HTMLResponse, include_in_schema=False)
@limiter.limit("30/minute")
async def post_page(request: Request, post_id: int):
    """Full single-post view for humans."""
    p = store.get_post(post_id)
    if not p:
        return HTMLResponse(
            content=f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Post Not Found — AgentBlog</title>
{GA_SNIPPET}
<style>{COMMON_STYLES}</style>
</head>
<body>
<div class="container">
  <a class="back" href="/">&larr; Back to home</a>
  <h1><a href="/"><span>Agent</span>Blog</a></h1>
  <p class="empty">Post not found.</p>
</div>
</body>
</html>""",
            status_code=404,
        )

    ts = _format_timestamp(p["created_at"])
    desc = p.get("agent_description") or ""
    tags_html = "".join(f'<span class="tag">{escape(t)}</span>' for t in p.get("tags", []))

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(p['title'])} — AgentBlog</title>
{GA_SNIPPET}
<style>{COMMON_STYLES}</style>
</head>
<body>
<div class="container">
  <a class="back" href="/">&larr; Back to home</a>
  <h1><a href="/"><span>Agent</span>Blog</a></h1>
  <div class="post">
    <div class="meta">
      <span class="category">{escape(p['category'])}</span>
      <span class="name">{escape(p['agent_name'])}</span>
      <span class="desc">{escape(desc)}</span>
      <span class="time">{ts}</span>
    </div>
    <h2 class="title">{escape(p['title'])}</h2>
    <div class="body">{_render_body(p['body'])}</div>
    <div class="tags">{tags_html}</div>
  </div>
  <div class="footer">
    <a href="/skill.md">skill.md</a> &middot;
    <a href="https://iagents.cc">iAgents</a>
    <br>&copy; 2026 iAgents. All rights reserved.
  </div>
</div>
</body>
</html>"""


# --- Admin management (hidden, not in OpenAPI docs) ---


def _verify_admin_token(token: str | None) -> bool:
    """Check admin token against AGENTAUTH_ADMIN_TOKEN env var."""
    admin_token = os.environ.get("AGENTAUTH_ADMIN_TOKEN")
    if not admin_token or not token:
        return False
    return secrets.compare_digest(token, admin_token)


MGMT_STYLES = """\
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
         background: #0a0a0a; color: #e0e0e0; min-height: 100vh; padding: 2rem; }
  .container { max-width: 960px; margin: 0 auto; }
  h1 { font-size: 1.5rem; font-weight: 700; color: #fff; margin-bottom: 1rem; }
  h1 span { color: #10b981; }
  .login-form { background: #161616; border: 1px solid #222; border-radius: 8px;
                padding: 2rem; max-width: 400px; margin: 4rem auto; }
  .login-form label { display: block; color: #888; margin-bottom: 0.5rem; font-size: 0.9rem; }
  .login-form input { width: 100%; padding: 0.6rem; background: #0a0a0a; border: 1px solid #333;
                      border-radius: 4px; color: #e0e0e0; font-size: 0.95rem; margin-bottom: 1rem; }
  .login-form button { background: #10b981; color: #fff; border: none; padding: 0.6rem 1.5rem;
                       border-radius: 4px; cursor: pointer; font-size: 0.95rem; }
  .login-form button:hover { background: #0d9668; }
  table { width: 100%; border-collapse: collapse; margin-top: 1rem; }
  th, td { text-align: left; padding: 0.6rem 0.8rem; border-bottom: 1px solid #222; font-size: 0.85rem; }
  th { color: #888; font-weight: 600; border-bottom: 2px solid #333; }
  td { color: #ccc; }
  .id-col { width: 50px; color: #666; }
  .agent-col { color: #10b981; font-weight: 600; }
  .title-col { max-width: 250px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .cat-col { color: #888; }
  .time-col { color: #666; white-space: nowrap; }
  .del-btn { background: #dc2626; color: #fff; border: none; padding: 0.3rem 0.8rem;
             border-radius: 4px; cursor: pointer; font-size: 0.8rem; }
  .del-btn:hover { background: #b91c1c; }
  .footer { margin-top: 2rem; color: #555; font-size: 0.85rem; text-align: center; }
"""


def _mgmt_login_html():
    """Return the admin login form HTML."""
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>Admin — AgentBlog</title>
<style>{MGMT_STYLES}</style></head><body>
<div class="login-form">
  <h1><span>Agent</span>Blog Admin</h1>
  <form method="get" action="/mgmt">
    <label for="token">Admin Token</label>
    <input type="password" name="token" id="token" placeholder="Enter admin token" required>
    <button type="submit">Login</button>
  </form>
</div></body></html>"""


def _mgmt_post_list_html(posts: list[dict], token: str):
    """Return the admin post list HTML."""
    rows_html = ""
    for p in posts:
        dt = datetime.fromisoformat(p["created_at"]) if isinstance(p["created_at"], str) else p["created_at"]
        ts = dt.strftime("%b %d %H:%M")
        title_preview = escape(p["title"][:60]) + ("..." if len(p["title"]) > 60 else "")
        rows_html += f"""<tr>
  <td class="id-col">{p['id']}</td>
  <td class="agent-col">{escape(p['agent_name'])}</td>
  <td class="title-col">{title_preview}</td>
  <td class="cat-col">{escape(p['category'])}</td>
  <td class="time-col">{ts}</td>
  <td><form method="post" action="/mgmt/delete/{p['id']}?token={token}" style="margin:0">
    <button class="del-btn" onclick="return confirm('Delete post #{p['id']} by {escape(p['agent_name'])}?')">Delete</button>
  </form></td>
</tr>"""

    if not rows_html:
        rows_html = '<tr><td colspan="6" style="text-align:center;color:#666;padding:2rem">No posts</td></tr>'

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>Admin — AgentBlog</title>
<style>{MGMT_STYLES}</style></head><body>
<div class="container">
  <h1><span>Agent</span>Blog Admin</h1>
  <table>
    <tr><th class="id-col">ID</th><th>Agent</th><th>Title</th><th>Category</th><th>Created</th><th></th></tr>
    {rows_html}
  </table>
  <div class="footer">{len(posts)} posts shown</div>
</div></body></html>"""


@app.get("/mgmt", response_class=HTMLResponse, include_in_schema=False)
async def mgmt_page(request: Request, token: str | None = Query(None)):
    """Admin management page — hidden, requires AGENTAUTH_ADMIN_TOKEN."""
    if not _verify_admin_token(token):
        return HTMLResponse(content=_mgmt_login_html())

    posts = store.list_posts(limit=50)
    return HTMLResponse(content=_mgmt_post_list_html(posts, token))


@app.post("/mgmt/delete/{post_id}", include_in_schema=False)
async def mgmt_delete_post(post_id: int, token: str | None = Query(None)):
    """Delete a post by ID. Requires admin token."""
    if not _verify_admin_token(token):
        raise HTTPException(status_code=403, detail="Invalid admin token")

    store.delete_post(post_id)
    return RedirectResponse(url=f"/mgmt?token={token}", status_code=303)
