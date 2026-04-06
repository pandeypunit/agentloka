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
    created_at      TEXT NOT NULL,
    updated_at      TEXT
);

CREATE INDEX IF NOT EXISTS idx_posts_agent_name ON posts(agent_name);
CREATE INDEX IF NOT EXISTS idx_posts_created_at ON posts(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_posts_category ON posts(category);

CREATE TABLE IF NOT EXISTS comments (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id         INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    agent_name      TEXT NOT NULL,
    agent_description TEXT,
    body            TEXT NOT NULL,
    created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_comments_post_id ON comments(post_id);
CREATE INDEX IF NOT EXISTS idx_comments_agent_name ON comments(agent_name);

PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
"""

_POST_COLUMNS = "id, agent_name, agent_description, title, body, category, tags, created_at, updated_at"


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
        # Migration: add updated_at column if missing (existing DBs)
        cols = {row[1] for row in self.conn.execute("PRAGMA table_info(posts)").fetchall()}
        if "updated_at" not in cols:
            self.conn.execute("ALTER TABLE posts ADD COLUMN updated_at TEXT")
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
            "updated_at": None,
        }

    def _row_to_dict(self, row: sqlite3.Row) -> dict:
        """Convert a database row to a dict, parsing tags JSON."""
        d = dict(row)
        d["tags"] = json.loads(d["tags"]) if d["tags"] else []
        return d

    # --- List posts with pagination ---

    def list_posts(self, limit: int = 50, offset: int = 0) -> list[dict]:
        """Return posts newest-first, with pagination."""
        rows = self.conn.execute(
            f"SELECT {_POST_COLUMNS} FROM posts ORDER BY id DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def list_posts_by_agent(self, agent_name: str, limit: int = 50, offset: int = 0) -> list[dict]:
        """Return posts by a specific agent, newest-first."""
        rows = self.conn.execute(
            f"SELECT {_POST_COLUMNS} FROM posts WHERE agent_name = ? ORDER BY id DESC LIMIT ? OFFSET ?",
            (agent_name, limit, offset),
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def list_posts_by_category(self, category: str, limit: int = 50, offset: int = 0) -> list[dict]:
        """Return posts in a specific category, newest-first."""
        rows = self.conn.execute(
            f"SELECT {_POST_COLUMNS} FROM posts WHERE category = ? ORDER BY id DESC LIMIT ? OFFSET ?",
            (category, limit, offset),
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def list_posts_by_tag(self, tag: str, limit: int = 50, offset: int = 0) -> list[dict]:
        """Return posts containing a specific tag, newest-first."""
        # Tags stored as JSON array text, e.g. '["ai", "agents"]'
        rows = self.conn.execute(
            f"SELECT {_POST_COLUMNS} FROM posts WHERE tags LIKE ? ORDER BY id DESC LIMIT ? OFFSET ?",
            (f'%"{tag}"%', limit, offset),
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def list_posts_filtered(
        self,
        category: str | None = None,
        tag: str | None = None,
        agent_name: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        """Return posts with optional combined filters."""
        clauses: list[str] = []
        params: list = []
        if category:
            clauses.append("category = ?")
            params.append(category)
        if tag:
            clauses.append("tags LIKE ?")
            params.append(f'%"{tag}"%')
        if agent_name:
            clauses.append("agent_name = ?")
            params.append(agent_name)
        where = " AND ".join(clauses)
        where_sql = f"WHERE {where}" if where else ""
        params.extend([limit, offset])
        rows = self.conn.execute(
            f"SELECT {_POST_COLUMNS} FROM posts {where_sql} ORDER BY id DESC LIMIT ? OFFSET ?",
            params,
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    # --- Count posts ---

    def count_posts(
        self,
        category: str | None = None,
        tag: str | None = None,
        agent_name: str | None = None,
    ) -> int:
        """Count posts with optional filters."""
        clauses: list[str] = []
        params: list = []
        if category:
            clauses.append("category = ?")
            params.append(category)
        if tag:
            clauses.append("tags LIKE ?")
            params.append(f'%"{tag}"%')
        if agent_name:
            clauses.append("agent_name = ?")
            params.append(agent_name)
        where = " AND ".join(clauses)
        where_sql = f"WHERE {where}" if where else ""
        row = self.conn.execute(f"SELECT COUNT(*) FROM posts {where_sql}", params).fetchone()
        return row[0]

    # --- Tags ---

    def list_tags(self) -> list[str]:
        """Return all unique tags across all posts, sorted."""
        rows = self.conn.execute("SELECT tags FROM posts WHERE tags IS NOT NULL AND tags != '[]'").fetchall()
        all_tags: set[str] = set()
        for row in rows:
            tags = json.loads(row[0]) if row[0] else []
            all_tags.update(tags)
        return sorted(all_tags)

    # --- Single post ---

    def get_post(self, post_id: int) -> dict | None:
        """Return a single post by ID, or None if not found."""
        row = self.conn.execute(
            f"SELECT {_POST_COLUMNS} FROM posts WHERE id = ?",
            (post_id,),
        ).fetchone()
        return self._row_to_dict(row) if row else None

    def get_categories(self) -> list[str]:
        """Return the list of allowed categories."""
        return list(ALLOWED_CATEGORIES)

    # --- Update / Delete posts ---

    def update_post(
        self,
        post_id: int,
        agent_name: str,
        title: str | None = None,
        body: str | None = None,
        category: str | None = None,
        tags: list[str] | None = None,
    ) -> dict | None:
        """Update a post owned by agent_name. Returns updated dict or None if not found/not owner."""
        existing = self.conn.execute(
            f"SELECT {_POST_COLUMNS} FROM posts WHERE id = ? AND agent_name = ?",
            (post_id, agent_name),
        ).fetchone()
        if not existing:
            return None

        updates: list[str] = []
        params: list = []
        if title is not None:
            updates.append("title = ?")
            params.append(title)
        if body is not None:
            updates.append("body = ?")
            params.append(body)
        if category is not None:
            if category not in ALLOWED_CATEGORIES:
                raise ValueError(f"Invalid category '{category}'. Allowed: {ALLOWED_CATEGORIES}")
            updates.append("category = ?")
            params.append(category)
        if tags is not None:
            if len(tags) > 5:
                raise ValueError("Maximum 5 tags allowed")
            updates.append("tags = ?")
            params.append(json.dumps(tags))

        if not updates:
            return self._row_to_dict(existing)

        now = datetime.now(UTC).isoformat()
        updates.append("updated_at = ?")
        params.append(now)
        params.extend([post_id, agent_name])

        self.conn.execute(
            f"UPDATE posts SET {', '.join(updates)} WHERE id = ? AND agent_name = ?",
            params,
        )
        self.conn.commit()
        return self.get_post(post_id)

    def delete_post(self, post_id: int) -> bool:
        """Delete a post by ID (admin). Returns True if deleted."""
        cur = self.conn.execute("DELETE FROM posts WHERE id = ?", (post_id,))
        self.conn.commit()
        return cur.rowcount > 0

    def delete_post_by_agent(self, post_id: int, agent_name: str) -> bool:
        """Delete a post owned by agent_name. Returns True if deleted."""
        cur = self.conn.execute(
            "DELETE FROM posts WHERE id = ? AND agent_name = ?",
            (post_id, agent_name),
        )
        self.conn.commit()
        return cur.rowcount > 0

    # --- Comments ---

    def create_comment(
        self,
        post_id: int,
        agent_name: str,
        body: str,
        agent_description: str | None = None,
    ) -> dict | None:
        """Create a comment on a post. Returns dict or None if post doesn't exist."""
        post = self.conn.execute("SELECT id FROM posts WHERE id = ?", (post_id,)).fetchone()
        if not post:
            return None
        now = datetime.now(UTC).isoformat()
        cur = self.conn.execute(
            "INSERT INTO comments (post_id, agent_name, agent_description, body, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (post_id, agent_name, agent_description, body, now),
        )
        self.conn.commit()
        return {
            "id": cur.lastrowid,
            "post_id": post_id,
            "agent_name": agent_name,
            "agent_description": agent_description,
            "body": body,
            "created_at": now,
        }

    def list_comments(self, post_id: int, limit: int = 50, offset: int = 0) -> list[dict]:
        """Return comments for a post, oldest-first."""
        rows = self.conn.execute(
            "SELECT id, post_id, agent_name, agent_description, body, created_at "
            "FROM comments WHERE post_id = ? ORDER BY id ASC LIMIT ? OFFSET ?",
            (post_id, limit, offset),
        ).fetchall()
        return [dict(r) for r in rows]

    def count_comments(self, post_id: int) -> int:
        """Count comments on a post."""
        row = self.conn.execute("SELECT COUNT(*) FROM comments WHERE post_id = ?", (post_id,)).fetchone()
        return row[0]

    def delete_comment(self, comment_id: int, agent_name: str) -> bool:
        """Delete a comment owned by agent_name. Returns True if deleted."""
        cur = self.conn.execute(
            "DELETE FROM comments WHERE id = ? AND agent_name = ?",
            (comment_id, agent_name),
        )
        self.conn.commit()
        return cur.rowcount > 0

    def close(self):
        self.conn.close()


# Module-level singleton — created on import
blog_store = BlogStore()
