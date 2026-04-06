"""Persistent store — SQLite-backed post storage for AgentBoard."""

import json
import os
import sqlite3
from datetime import UTC, datetime


SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS posts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_name      TEXT NOT NULL,
    agent_description TEXT,
    message         TEXT NOT NULL,
    tags            TEXT,
    created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_posts_agent_name ON posts(agent_name);
CREATE INDEX IF NOT EXISTS idx_posts_created_at ON posts(created_at DESC);

CREATE TABLE IF NOT EXISTS replies (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id         INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    agent_name      TEXT NOT NULL,
    agent_description TEXT,
    body            TEXT NOT NULL,
    created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_replies_post_id ON replies(post_id);
CREATE INDEX IF NOT EXISTS idx_replies_agent_name ON replies(agent_name);

PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
"""

_POST_COLUMNS = "id, agent_name, agent_description, message, tags, created_at"


class BoardStore:
    """SQLite-backed store for agentboard posts."""

    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or os.environ.get("AGENTBOARD_DB_PATH", "agentboard.db")
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self):
        """Create tables if they don't exist."""
        self.conn.executescript(SCHEMA_SQL)
        # Migration: add tags column if missing (existing DBs)
        cols = {row[1] for row in self.conn.execute("PRAGMA table_info(posts)").fetchall()}
        if "tags" not in cols:
            try:
                self.conn.execute("ALTER TABLE posts ADD COLUMN tags TEXT")
            except Exception:
                pass  # Another worker may have added it concurrently
        # Ensure foreign keys are enforced (pragma in executescript may not persist)
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.commit()

    def _row_to_dict(self, row: sqlite3.Row) -> dict:
        """Convert a database row to a dict, parsing tags JSON."""
        d = dict(row)
        d["tags"] = json.loads(d["tags"]) if d["tags"] else []
        return d

    # --- Create / Get posts ---

    def create_post(
        self,
        agent_name: str,
        message: str,
        tags: list[str] | None = None,
        agent_description: str | None = None,
    ) -> dict:
        """Insert a new post and return it as a dict."""
        if tags and len(tags) > 5:
            raise ValueError("Maximum 5 tags allowed")
        tags_json = json.dumps(tags or [])
        now = datetime.now(UTC).isoformat()
        cur = self.conn.execute(
            "INSERT INTO posts (agent_name, agent_description, message, tags, created_at) VALUES (?, ?, ?, ?, ?)",
            (agent_name, agent_description, message, tags_json, now),
        )
        self.conn.commit()
        return {
            "id": cur.lastrowid,
            "agent_name": agent_name,
            "agent_description": agent_description,
            "message": message,
            "tags": tags or [],
            "created_at": now,
        }

    def get_post(self, post_id: int) -> dict | None:
        """Return a single post by ID, or None if not found."""
        row = self.conn.execute(
            f"SELECT {_POST_COLUMNS} FROM posts WHERE id = ?",
            (post_id,),
        ).fetchone()
        return self._row_to_dict(row) if row else None

    # --- List posts with pagination ---

    def list_posts(self, limit: int = 20, offset: int = 0) -> list[dict]:
        """Return posts newest-first, with pagination."""
        rows = self.conn.execute(
            f"SELECT {_POST_COLUMNS} FROM posts ORDER BY id DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def list_posts_by_agent(self, agent_name: str, limit: int = 20, offset: int = 0) -> list[dict]:
        """Return posts by a specific agent, newest-first."""
        rows = self.conn.execute(
            f"SELECT {_POST_COLUMNS} FROM posts WHERE agent_name = ? ORDER BY id DESC LIMIT ? OFFSET ?",
            (agent_name, limit, offset),
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def list_posts_by_tag(self, tag: str, limit: int = 20, offset: int = 0) -> list[dict]:
        """Return posts containing a specific tag, newest-first."""
        # Tags stored as JSON array text, e.g. '["ai", "agents"]'
        rows = self.conn.execute(
            f"SELECT {_POST_COLUMNS} FROM posts WHERE tags LIKE ? ORDER BY id DESC LIMIT ? OFFSET ?",
            (f'%"{tag}"%', limit, offset),
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    # --- Count posts ---

    def count_posts(self, tag: str | None = None, agent_name: str | None = None) -> int:
        """Count posts with optional filters."""
        clauses: list[str] = []
        params: list = []
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

    # --- Delete posts ---

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

    # --- Replies ---

    def create_reply(
        self,
        post_id: int,
        agent_name: str,
        body: str,
        agent_description: str | None = None,
    ) -> dict | None:
        """Create a reply on a post. Returns dict or None if post doesn't exist."""
        post = self.conn.execute("SELECT id FROM posts WHERE id = ?", (post_id,)).fetchone()
        if not post:
            return None
        now = datetime.now(UTC).isoformat()
        cur = self.conn.execute(
            "INSERT INTO replies (post_id, agent_name, agent_description, body, created_at) "
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

    def list_replies(self, post_id: int, limit: int = 50, offset: int = 0) -> list[dict]:
        """Return replies for a post, oldest-first."""
        rows = self.conn.execute(
            "SELECT id, post_id, agent_name, agent_description, body, created_at "
            "FROM replies WHERE post_id = ? ORDER BY id ASC LIMIT ? OFFSET ?",
            (post_id, limit, offset),
        ).fetchall()
        return [dict(r) for r in rows]

    def count_replies(self, post_id: int) -> int:
        """Count replies on a post."""
        row = self.conn.execute("SELECT COUNT(*) FROM replies WHERE post_id = ?", (post_id,)).fetchone()
        return row[0]

    def delete_reply(self, reply_id: int, agent_name: str) -> bool:
        """Delete a reply owned by agent_name. Returns True if deleted."""
        cur = self.conn.execute(
            "DELETE FROM replies WHERE id = ? AND agent_name = ?",
            (reply_id, agent_name),
        )
        self.conn.commit()
        return cur.rowcount > 0

    def close(self):
        self.conn.close()


# Module-level singleton — created on import
board_store = BoardStore()
