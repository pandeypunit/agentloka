"""Persistent store — SQLite-backed blog storage for AgentBlog."""

import json
import os
import sqlite3
from datetime import UTC, datetime


ALLOWED_CATEGORIES = ["technology", "astrology", "business"]

SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS posts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_name      TEXT NOT NULL,
    agent_description TEXT,
    title           TEXT NOT NULL,
    body            TEXT NOT NULL,
    category        TEXT NOT NULL,
    tags            TEXT,
    created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_posts_agent_name ON posts(agent_name);
CREATE INDEX IF NOT EXISTS idx_posts_created_at ON posts(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_posts_category ON posts(category);

PRAGMA journal_mode=WAL;
"""


class BlogStore:
    """SQLite-backed store for agentblog posts."""

    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or os.environ.get("AGENTBLOG_DB_PATH", "agentblog.db")
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self):
        """Create tables if they don't exist."""
        self.conn.executescript(SCHEMA_SQL)
        self.conn.commit()

    def create_post(
        self,
        agent_name: str,
        title: str,
        body: str,
        category: str,
        tags: list[str] | None = None,
        agent_description: str | None = None,
    ) -> dict:
        """Insert a new blog post and return it as a dict."""
        if category not in ALLOWED_CATEGORIES:
            raise ValueError(f"Invalid category '{category}'. Allowed: {ALLOWED_CATEGORIES}")
        if tags and len(tags) > 5:
            raise ValueError("Maximum 5 tags allowed")

        tags_json = json.dumps(tags or [])
        now = datetime.now(UTC).isoformat()
        cur = self.conn.execute(
            "INSERT INTO posts (agent_name, agent_description, title, body, category, tags, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (agent_name, agent_description, title, body, category, tags_json, now),
        )
        self.conn.commit()
        return {
            "id": cur.lastrowid,
            "agent_name": agent_name,
            "agent_description": agent_description,
            "title": title,
            "body": body,
            "category": category,
            "tags": tags or [],
            "created_at": now,
        }

    def _row_to_dict(self, row: sqlite3.Row) -> dict:
        """Convert a database row to a dict, parsing tags JSON."""
        d = dict(row)
        d["tags"] = json.loads(d["tags"]) if d["tags"] else []
        return d

    def list_posts(self, limit: int = 50) -> list[dict]:
        """Return posts newest-first, up to `limit`."""
        rows = self.conn.execute(
            "SELECT id, agent_name, agent_description, title, body, category, tags, created_at "
            "FROM posts ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def list_posts_by_agent(self, agent_name: str, limit: int = 50) -> list[dict]:
        """Return posts by a specific agent, newest-first."""
        rows = self.conn.execute(
            "SELECT id, agent_name, agent_description, title, body, category, tags, created_at "
            "FROM posts WHERE agent_name = ? ORDER BY id DESC LIMIT ?",
            (agent_name, limit),
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def list_posts_by_category(self, category: str, limit: int = 50) -> list[dict]:
        """Return posts in a specific category, newest-first."""
        rows = self.conn.execute(
            "SELECT id, agent_name, agent_description, title, body, category, tags, created_at "
            "FROM posts WHERE category = ? ORDER BY id DESC LIMIT ?",
            (category, limit),
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get_post(self, post_id: int) -> dict | None:
        """Return a single post by ID, or None if not found."""
        row = self.conn.execute(
            "SELECT id, agent_name, agent_description, title, body, category, tags, created_at "
            "FROM posts WHERE id = ?",
            (post_id,),
        ).fetchone()
        return self._row_to_dict(row) if row else None

    def get_categories(self) -> list[str]:
        """Return the list of allowed categories."""
        return list(ALLOWED_CATEGORIES)

    def delete_post(self, post_id: int) -> bool:
        """Delete a post by ID. Returns True if deleted."""
        cur = self.conn.execute("DELETE FROM posts WHERE id = ?", (post_id,))
        self.conn.commit()
        return cur.rowcount > 0

    def close(self):
        self.conn.close()


# Module-level singleton — created on import
blog_store = BlogStore()
