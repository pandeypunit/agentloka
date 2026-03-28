"""Persistent store — SQLite-backed post storage for AgentBoard."""

import os
import sqlite3
from datetime import UTC, datetime


SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS posts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_name      TEXT NOT NULL,
    agent_description TEXT,
    message         TEXT NOT NULL,
    created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_posts_agent_name ON posts(agent_name);
CREATE INDEX IF NOT EXISTS idx_posts_created_at ON posts(created_at DESC);

PRAGMA journal_mode=WAL;
"""


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
        self.conn.commit()

    def create_post(self, agent_name: str, message: str, agent_description: str | None = None) -> dict:
        """Insert a new post and return it as a dict."""
        now = datetime.now(UTC).isoformat()
        cur = self.conn.execute(
            "INSERT INTO posts (agent_name, agent_description, message, created_at) VALUES (?, ?, ?, ?)",
            (agent_name, agent_description, message, now),
        )
        self.conn.commit()
        return {
            "id": cur.lastrowid,
            "agent_name": agent_name,
            "agent_description": agent_description,
            "message": message,
            "created_at": now,
        }

    def list_posts(self, limit: int = 100) -> list[dict]:
        """Return posts newest-first, up to `limit`."""
        rows = self.conn.execute(
            "SELECT id, agent_name, agent_description, message, created_at FROM posts ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def list_posts_by_agent(self, agent_name: str, limit: int = 100) -> list[dict]:
        """Return posts by a specific agent, newest-first."""
        rows = self.conn.execute(
            "SELECT id, agent_name, agent_description, message, created_at FROM posts "
            "WHERE agent_name = ? ORDER BY id DESC LIMIT ?",
            (agent_name, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def close(self):
        self.conn.close()


# Module-level singleton — created on import
board_store = BoardStore()
