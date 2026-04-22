"""Persistent store — SQLite-backed direct-message storage for AgentMessenger."""

import os
import sqlite3
from datetime import UTC, datetime, timedelta


SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS messages (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    from_agent   TEXT NOT NULL,
    to_agent     TEXT NOT NULL,
    body         TEXT NOT NULL,
    reply_to_id  INTEGER REFERENCES messages(id) ON DELETE SET NULL,
    created_at   TEXT NOT NULL,
    read_at      TEXT
);

-- Inbox queries (by-day and id-range scans for a recipient).
CREATE INDEX IF NOT EXISTS idx_msg_to_created
    ON messages(to_agent, created_at DESC);

-- Partial index keeps unread fetches O(unread), not O(inbox).
CREATE INDEX IF NOT EXISTS idx_msg_to_unread
    ON messages(to_agent, created_at) WHERE read_at IS NULL;

-- Outbox queries.
CREATE INDEX IF NOT EXISTS idx_msg_from_created
    ON messages(from_agent, created_at DESC);

-- Reply chain lookups.
CREATE INDEX IF NOT EXISTS idx_msg_reply_to
    ON messages(reply_to_id);

PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
"""

_MSG_COLUMNS = "id, from_agent, to_agent, body, reply_to_id, created_at, read_at"


class MessengerStore:
    """SQLite-backed store for direct messages between agents."""

    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or os.environ.get("AGENTMESSENGER_DB_PATH", "agentmessenger.db")
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self):
        """Create tables and indexes if they don't exist."""
        self.conn.executescript(SCHEMA_SQL)
        # PRAGMAs in executescript may not stick in some SQLite builds — re-enable explicitly.
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.commit()

    @staticmethod
    def _row(row: sqlite3.Row) -> dict:
        return dict(row) if row else None

    # --- Send ---

    def create_message(
        self,
        from_agent: str,
        to_agent: str,
        body: str,
        reply_to_id: int | None = None,
    ) -> dict:
        """Insert a new message. Caller is responsible for validating the recipient
        and for ensuring reply_to_id (if given) refers to an existing message."""
        now = datetime.now(UTC).isoformat()
        cur = self.conn.execute(
            "INSERT INTO messages (from_agent, to_agent, body, reply_to_id, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (from_agent, to_agent, body, reply_to_id, now),
        )
        self.conn.commit()
        return {
            "id": cur.lastrowid,
            "from_agent": from_agent,
            "to_agent": to_agent,
            "body": body,
            "reply_to_id": reply_to_id,
            "created_at": now,
            "read_at": None,
        }

    # --- Single lookup ---

    def get_message(self, message_id: int) -> dict | None:
        """Return a single message by id, or None."""
        row = self.conn.execute(
            f"SELECT {_MSG_COLUMNS} FROM messages WHERE id = ?",
            (message_id,),
        ).fetchone()
        return self._row(row)

    # --- Unread inbox (auto-marks read) ---

    def list_unread_and_mark_read(
        self, to_agent: str, limit: int = 50, offset: int = 0
    ) -> list[dict]:
        """Atomically fetch a page of unread messages for `to_agent` and mark them read.
        Returns the rows with `read_at` populated to the timestamp just set."""
        # Read + write in a single transaction so a concurrent caller cannot see the same
        # rows twice (SQLite serializes writers; reads inside the txn see consistent state).
        with self.conn:
            rows = self.conn.execute(
                f"SELECT {_MSG_COLUMNS} FROM messages "
                "WHERE to_agent = ? AND read_at IS NULL "
                "ORDER BY id ASC LIMIT ? OFFSET ?",
                (to_agent, limit, offset),
            ).fetchall()
            if not rows:
                return []
            now = datetime.now(UTC).isoformat()
            ids = [r["id"] for r in rows]
            placeholders = ",".join("?" * len(ids))
            self.conn.execute(
                f"UPDATE messages SET read_at = ? WHERE id IN ({placeholders})",
                (now, *ids),
            )
        # Return dicts with the freshly-set read_at.
        result = []
        for r in rows:
            d = dict(r)
            d["read_at"] = now
            result.append(d)
        return result

    def count_unread(self, to_agent: str) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) FROM messages WHERE to_agent = ? AND read_at IS NULL",
            (to_agent,),
        ).fetchone()
        return row[0]

    # --- By-day inbox (does NOT mark read) ---

    @staticmethod
    def _day_bounds(day_iso: str) -> tuple[str, str]:
        """Return [start, end) ISO strings for a UTC day given as YYYY-MM-DD."""
        day = datetime.strptime(day_iso, "%Y-%m-%d").replace(tzinfo=UTC)
        return day.isoformat(), (day + timedelta(days=1)).isoformat()

    def list_by_day(
        self, to_agent: str, day_iso: str, limit: int = 50, offset: int = 0
    ) -> list[dict]:
        """Return received messages on a single UTC day, newest-first."""
        start, end = self._day_bounds(day_iso)
        rows = self.conn.execute(
            f"SELECT {_MSG_COLUMNS} FROM messages "
            "WHERE to_agent = ? AND created_at >= ? AND created_at < ? "
            "ORDER BY id DESC LIMIT ? OFFSET ?",
            (to_agent, start, end, limit, offset),
        ).fetchall()
        return [dict(r) for r in rows]

    def count_by_day(self, to_agent: str, day_iso: str) -> int:
        start, end = self._day_bounds(day_iso)
        row = self.conn.execute(
            "SELECT COUNT(*) FROM messages "
            "WHERE to_agent = ? AND created_at >= ? AND created_at < ?",
            (to_agent, start, end),
        ).fetchone()
        return row[0]

    # --- Outbox (sent) ---

    def list_sent(self, from_agent: str, limit: int = 50, offset: int = 0) -> list[dict]:
        """Return messages sent by `from_agent`, newest-first."""
        rows = self.conn.execute(
            f"SELECT {_MSG_COLUMNS} FROM messages "
            "WHERE from_agent = ? ORDER BY id DESC LIMIT ? OFFSET ?",
            (from_agent, limit, offset),
        ).fetchall()
        return [dict(r) for r in rows]

    def count_sent(self, from_agent: str) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) FROM messages WHERE from_agent = ?",
            (from_agent,),
        ).fetchone()
        return row[0]

    def close(self):
        self.conn.close()


# Module-level singleton — created on import.
messenger_store = MessengerStore()
