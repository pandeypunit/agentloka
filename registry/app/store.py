"""Persistent store — SQLite-backed, bcrypt-hashed API keys."""

import os
import secrets
import sqlite3
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
    load_pem_private_key,
)

from registry.app.models import AgentResponse, PlatformResponse

PROOF_TOKEN_TTL_SECONDS = 300  # 5 minutes — reusable until expiry

SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS agents (
    name            TEXT PRIMARY KEY,
    description     TEXT,
    api_key_hash    TEXT NOT NULL,
    api_key_prefix  TEXT NOT NULL,
    verified        INTEGER NOT NULL DEFAULT 0,
    email           TEXT,
    created_at      TEXT NOT NULL,
    active          INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_api_key_prefix ON agents(api_key_prefix);

CREATE TABLE IF NOT EXISTS pending_verifications (
    token       TEXT PRIMARY KEY,
    agent_name  TEXT NOT NULL REFERENCES agents(name) ON DELETE CASCADE,
    email       TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS server_metadata (
    key     TEXT PRIMARY KEY,
    value   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS platforms (
    name              TEXT PRIMARY KEY,
    domain            TEXT NOT NULL,
    description       TEXT,
    email             TEXT,
    secret_key_hash   TEXT NOT NULL,
    secret_key_prefix TEXT NOT NULL,
    verified          INTEGER NOT NULL DEFAULT 0,
    created_at        TEXT NOT NULL,
    active            INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_platform_key_prefix ON platforms(secret_key_prefix);

CREATE TABLE IF NOT EXISTS platform_pending_verifications (
    token         TEXT PRIMARY KEY,
    platform_name TEXT NOT NULL,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_reports (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_name    TEXT NOT NULL REFERENCES agents(name) ON DELETE CASCADE,
    platform_name TEXT NOT NULL REFERENCES platforms(name) ON DELETE CASCADE,
    reported_at   TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_one_report_per_platform
    ON agent_reports(agent_name, platform_name);
"""


class RegistryStore:
    """SQLite-backed store for agents. API keys are bcrypt-hashed."""

    def __init__(self, db_path: str | None = None):
        if db_path is None:
            db_path = os.environ.get("AGENTAUTH_DB_PATH", "agentauth.db")
        self._db = sqlite3.connect(db_path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._init_db()
        self._signing_key = self._load_or_create_signing_key()

    def _init_db(self):
        self._db.executescript(SCHEMA_SQL)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA foreign_keys=ON")
        self._db.commit()

    def _load_or_create_signing_key(self) -> ec.EllipticCurvePrivateKey:
        row = self._db.execute(
            "SELECT value FROM server_metadata WHERE key = 'signing_key_pem'"
        ).fetchone()
        if row:
            return load_pem_private_key(row["value"].encode(), password=None)
        key = ec.generate_private_key(ec.SECP256R1())
        pem = key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()).decode()
        self._db.execute(
            "INSERT INTO server_metadata (key, value) VALUES ('signing_key_pem', ?)", (pem,)
        )
        self._db.commit()
        return key

    @property
    def public_key_pem(self) -> str:
        return self._signing_key.public_key().public_bytes(
            Encoding.PEM, PublicFormat.SubjectPublicKeyInfo
        ).decode()

    @staticmethod
    def _generate_api_key() -> str:
        return "agentauth_" + secrets.token_hex(24)

    @staticmethod
    def _generate_verification_token() -> str:
        return secrets.token_urlsafe(32)

    @staticmethod
    def _hash_api_key(api_key: str) -> str:
        return bcrypt.hashpw(api_key.encode(), bcrypt.gensalt()).decode()

    @staticmethod
    def _check_api_key(api_key: str, api_key_hash: str) -> bool:
        return bcrypt.checkpw(api_key.encode(), api_key_hash.encode())

    @staticmethod
    def _api_key_prefix(api_key: str) -> str:
        return api_key[10:18]

    def _row_to_agent(self, row, registry_secret_key: str | None = None) -> AgentResponse:
        return AgentResponse(
            name=row["name"],
            description=row["description"],
            registry_secret_key=registry_secret_key,
            verified=bool(row["verified"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            active=bool(row["active"]),
        )

    def register_agent(
        self, name: str, description: str | None, email: str | None = None
    ) -> tuple[AgentResponse | None, str | None]:
        """Register a new agent. Returns (agent, verification_token) or (None, None) if name is taken."""
        existing = self._db.execute("SELECT 1 FROM agents WHERE name = ?", (name,)).fetchone()
        if existing:
            return None, None

        api_key = self._generate_api_key()
        now = datetime.now(UTC).isoformat()

        self._db.execute(
            "INSERT INTO agents (name, description, api_key_hash, api_key_prefix, verified, created_at, active) "
            "VALUES (?, ?, ?, ?, 0, ?, 1)",
            (name, description, self._hash_api_key(api_key), self._api_key_prefix(api_key), now),
        )

        verification_token = None
        if email:
            verification_token = self._generate_verification_token()
            self._db.execute(
                "INSERT INTO pending_verifications (token, agent_name, email, created_at) VALUES (?, ?, ?, ?)",
                (verification_token, name, email, now),
            )

        self._db.commit()

        proof_token = self.create_proof_token(name)
        agent = AgentResponse(
            name=name,
            description=description,
            registry_secret_key=api_key,
            platform_proof_token=proof_token,
            platform_proof_token_expires_in_seconds=PROOF_TOKEN_TTL_SECONDS,
            important="⚠️ SAVE YOUR registry_secret_key! It is shown ONLY ONCE. NEVER send it to any platform — use platform_proof_token instead.",
            verified=False,
            created_at=datetime.fromisoformat(now),
            active=True,
        )
        return agent, verification_token

    def verify_email(self, token: str) -> str | None:
        """Verify an email token. Returns agent name on success, None on failure."""
        row = self._db.execute(
            "SELECT agent_name, email FROM pending_verifications WHERE token = ?", (token,)
        ).fetchone()
        if not row:
            return None

        agent_name = row["agent_name"]
        email = row["email"]

        agent_exists = self._db.execute(
            "SELECT 1 FROM agents WHERE name = ?", (agent_name,)
        ).fetchone()
        if not agent_exists:
            return None

        self._db.execute("DELETE FROM pending_verifications WHERE token = ?", (token,))
        self._db.execute(
            "UPDATE agents SET verified = 1, email = ? WHERE name = ?", (email, agent_name)
        )
        self._db.commit()
        return agent_name

    def link_email(self, agent_name: str, email: str) -> str:
        """Link an email to an existing agent. Returns a verification token."""
        token = self._generate_verification_token()
        now = datetime.now(UTC).isoformat()
        self._db.execute(
            "INSERT INTO pending_verifications (token, agent_name, email, created_at) VALUES (?, ?, ?, ?)",
            (token, agent_name, email, now),
        )
        self._db.commit()
        return token

    def create_proof_token(self, agent_name: str) -> str:
        """Create a JWT proof token for an agent. Reusable until expiry."""
        row = self._db.execute(
            "SELECT description, verified FROM agents WHERE name = ?", (agent_name,)
        ).fetchone()
        now = datetime.now(UTC).timestamp()
        payload = {
            "sub": agent_name,
            "description": row["description"] if row else None,
            "verified": bool(row["verified"]) if row else False,
            "iat": int(now),
            "exp": int(now) + PROOF_TOKEN_TTL_SECONDS,
        }
        return jwt.encode(payload, self._signing_key, algorithm="ES256")

    def verify_proof_token(self, token: str) -> dict | None:
        """Verify a JWT proof token. Returns decoded payload or None."""
        try:
            payload = jwt.decode(
                token, self._signing_key.public_key(), algorithms=["ES256"]
            )
        except jwt.InvalidTokenError:
            return None
        agent_name = payload.get("sub")
        exists = self._db.execute(
            "SELECT 1 FROM agents WHERE name = ?", (agent_name,)
        ).fetchone()
        if not exists:
            return None
        return payload

    def get_agent(self, name: str) -> AgentResponse | None:
        row = self._db.execute(
            "SELECT name, description, verified, created_at, active FROM agents WHERE name = ?",
            (name,),
        ).fetchone()
        if not row:
            return None
        agent = self._row_to_agent(row)
        # Attach report data to public profile
        reports = self.get_agent_reports(name)
        agent.report_count = reports["report_count"]
        agent.reporting_platforms = reports["reporting_platforms"]
        return agent

    def get_agent_by_key(self, api_key: str) -> AgentResponse | None:
        prefix = self._api_key_prefix(api_key)
        rows = self._db.execute(
            "SELECT name, description, api_key_hash, verified, created_at, active "
            "FROM agents WHERE api_key_prefix = ? AND active = 1",
            (prefix,),
        ).fetchall()
        for row in rows:
            if self._check_api_key(api_key, row["api_key_hash"]):
                return self._row_to_agent(row)
        return None

    def list_agents(self) -> list[AgentResponse]:
        rows = self._db.execute(
            "SELECT name, description, verified, created_at, active FROM agents"
        ).fetchall()
        return [self._row_to_agent(row) for row in rows]

    def revoke_agent(self, name: str, api_key: str) -> bool:
        """Revoke an agent. Must provide the correct API key."""
        row = self._db.execute(
            "SELECT api_key_hash FROM agents WHERE name = ?", (name,)
        ).fetchone()
        if not row or not self._check_api_key(api_key, row["api_key_hash"]):
            return False
        self._db.execute("DELETE FROM agents WHERE name = ?", (name,))
        self._db.commit()
        return True

    # --- Platform registration (mirrors agent pattern) ---

    @staticmethod
    def _generate_platform_key() -> str:
        """Generate a platform secret key with platauth_ prefix."""
        return "platauth_" + secrets.token_hex(24)

    @staticmethod
    def _platform_key_prefix(key: str) -> str:
        """Extract prefix from a platauth_ key for indexed lookup."""
        return key[10:18]

    def _row_to_platform(self, row, platform_secret_key: str | None = None) -> PlatformResponse:
        return PlatformResponse(
            name=row["name"],
            domain=row["domain"],
            description=row["description"] if "description" in row.keys() else None,
            platform_secret_key=platform_secret_key,
            verified=bool(row["verified"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            active=bool(row["active"]),
        )

    def register_platform(
        self, name: str, domain: str, description: str | None = None, email: str | None = None
    ) -> tuple[PlatformResponse | None, str | None]:
        """Register a new platform. Returns (platform, verification_token) or (None, None) if name is taken."""
        existing = self._db.execute("SELECT 1 FROM platforms WHERE name = ?", (name,)).fetchone()
        if existing:
            return None, None

        key = self._generate_platform_key()
        now = datetime.now(UTC).isoformat()

        self._db.execute(
            "INSERT INTO platforms (name, domain, description, email, secret_key_hash, secret_key_prefix, verified, created_at, active) "
            "VALUES (?, ?, ?, ?, ?, ?, 0, ?, 1)",
            (name, domain, description, email, self._hash_api_key(key), self._platform_key_prefix(key), now),
        )

        verification_token = None
        if email:
            verification_token = self._generate_verification_token()
            self._db.execute(
                "INSERT INTO platform_pending_verifications (token, platform_name, created_at) VALUES (?, ?, ?)",
                (verification_token, name, now),
            )

        self._db.commit()

        platform = PlatformResponse(
            name=name,
            domain=domain,
            description=description,
            platform_secret_key=key,
            important="⚠️ SAVE YOUR platform_secret_key! It is shown ONLY ONCE.",
            verified=False,
            created_at=datetime.fromisoformat(now),
            active=True,
        )
        return platform, verification_token

    def get_platform(self, name: str) -> PlatformResponse | None:
        """Look up a platform by name. Public — no secret key in response."""
        row = self._db.execute(
            "SELECT name, domain, description, verified, created_at, active FROM platforms WHERE name = ?",
            (name,),
        ).fetchone()
        if not row:
            return None
        return self._row_to_platform(row)

    def list_platforms(self) -> list[PlatformResponse]:
        """List all active platforms. Public."""
        rows = self._db.execute(
            "SELECT name, domain, description, verified, created_at, active FROM platforms WHERE active = 1"
        ).fetchall()
        return [self._row_to_platform(row) for row in rows]

    def get_platform_by_key(self, secret_key: str) -> PlatformResponse | None:
        """Look up a platform by its secret key. Used for auth."""
        prefix = self._platform_key_prefix(secret_key)
        rows = self._db.execute(
            "SELECT name, domain, secret_key_hash, verified, created_at, active "
            "FROM platforms WHERE secret_key_prefix = ? AND active = 1",
            (prefix,),
        ).fetchall()
        for row in rows:
            if self._check_api_key(secret_key, row["secret_key_hash"]):
                return self._row_to_platform(row)
        return None

    def revoke_platform(self, name: str, secret_key: str) -> bool:
        """Revoke a platform. Must provide the correct secret key."""
        row = self._db.execute(
            "SELECT secret_key_hash FROM platforms WHERE name = ?", (name,)
        ).fetchone()
        if not row or not self._check_api_key(secret_key, row["secret_key_hash"]):
            return False
        self._db.execute("DELETE FROM platforms WHERE name = ?", (name,))
        self._db.commit()
        return True

    def verify_platform_email(self, token: str) -> str | None:
        """Verify a platform email token. Returns platform name on success, None on failure."""
        row = self._db.execute(
            "SELECT platform_name FROM platform_pending_verifications WHERE token = ?", (token,)
        ).fetchone()
        if not row:
            return None

        platform_name = row["platform_name"]
        platform_exists = self._db.execute(
            "SELECT 1 FROM platforms WHERE name = ?", (platform_name,)
        ).fetchone()
        if not platform_exists:
            return None

        self._db.execute("DELETE FROM platform_pending_verifications WHERE token = ?", (token,))
        self._db.execute(
            "UPDATE platforms SET verified = 1 WHERE name = ?", (platform_name,)
        )
        self._db.commit()
        return platform_name

    # --- Platform test helpers ---

    def get_platform_pending_verification_token(self, platform_name: str) -> str | None:
        """Get the pending verification token for a platform (if any)."""
        row = self._db.execute(
            "SELECT token FROM platform_pending_verifications WHERE platform_name = ?",
            (platform_name,),
        ).fetchone()
        return row["token"] if row else None

    # --- Agent reports (by registered platforms) ---

    def report_agent(self, agent_name: str, platform_name: str) -> bool:
        """File a report against an agent. Returns False if already reported by this platform."""
        now = datetime.now(UTC).isoformat()
        try:
            self._db.execute(
                "INSERT INTO agent_reports (agent_name, platform_name, reported_at) VALUES (?, ?, ?)",
                (agent_name, platform_name, now),
            )
            self._db.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def retract_report(self, agent_name: str, platform_name: str) -> bool:
        """Retract a report. Returns False if no report exists from this platform."""
        cursor = self._db.execute(
            "DELETE FROM agent_reports WHERE agent_name = ? AND platform_name = ?",
            (agent_name, platform_name),
        )
        self._db.commit()
        return cursor.rowcount > 0

    def get_agent_reports(self, agent_name: str) -> dict:
        """Get report summary for an agent."""
        rows = self._db.execute(
            "SELECT platform_name FROM agent_reports WHERE agent_name = ? ORDER BY reported_at",
            (agent_name,),
        ).fetchall()
        platforms = [row["platform_name"] for row in rows]
        return {
            "agent_name": agent_name,
            "report_count": len(platforms),
            "reporting_platforms": platforms,
        }

    # --- Admin reporting ---

    def get_admin_stats(self, from_date: str | None = None, to_date: str | None = None) -> dict:
        """Aggregate stats for admin reporting. Optional date range for filtered count."""
        now = datetime.now(UTC)

        row = self._db.execute(
            "SELECT COUNT(*) as total,"
            " SUM(CASE WHEN active=1 THEN 1 ELSE 0 END) as active,"
            " SUM(CASE WHEN active=0 THEN 1 ELSE 0 END) as revoked,"
            " SUM(CASE WHEN verified=1 THEN 1 ELSE 0 END) as verified,"
            " SUM(CASE WHEN verified=0 THEN 1 ELSE 0 END) as unverified"
            " FROM agents"
        ).fetchone()
        stats = {k: (row[k] or 0) for k in ("total", "active", "revoked", "verified", "unverified")}

        stats["pending_verifications"] = self.count_pending_verifications()

        for label, days in (("registrations_last_7d", 7), ("registrations_last_30d", 30)):
            cutoff = (now - timedelta(days=days)).isoformat()
            r = self._db.execute(
                "SELECT COUNT(*) as cnt FROM agents WHERE created_at >= ?", (cutoff,)
            ).fetchone()
            stats[label] = r["cnt"]

        # Optional date range filter
        if from_date and to_date:
            r = self._db.execute(
                "SELECT COUNT(*) as cnt FROM agents WHERE created_at >= ? AND created_at < ?",
                (from_date, to_date + "T23:59:59"),
            ).fetchone()
            stats["registrations_in_range"] = r["cnt"]
            stats["range_from"] = from_date
            stats["range_to"] = to_date

        newest = self._db.execute(
            "SELECT name, created_at FROM agents ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        stats["newest_agent"] = {"name": newest["name"], "created_at": newest["created_at"]} if newest else None

        # Platform stats
        plat_row = self._db.execute(
            "SELECT COUNT(*) as total,"
            " SUM(CASE WHEN active=1 THEN 1 ELSE 0 END) as active,"
            " SUM(CASE WHEN verified=1 THEN 1 ELSE 0 END) as verified"
            " FROM platforms"
        ).fetchone()
        stats["platforms_total"] = plat_row["total"] or 0
        stats["platforms_active"] = plat_row["active"] or 0
        stats["platforms_verified"] = plat_row["verified"] or 0

        stats["generated_at"] = now.isoformat()
        return stats

    # --- Test helpers ---

    def get_pending_verification_token(self, agent_name: str) -> str | None:
        """Get the pending verification token for an agent (if any)."""
        row = self._db.execute(
            "SELECT token FROM pending_verifications WHERE agent_name = ?", (agent_name,)
        ).fetchone()
        return row["token"] if row else None

    def get_verified_email(self, agent_name: str) -> str | None:
        """Get the verified email for an agent (if any)."""
        row = self._db.execute(
            "SELECT email FROM agents WHERE name = ? AND verified = 1", (agent_name,)
        ).fetchone()
        return row["email"] if row else None

    def count_pending_verifications(self) -> int:
        """Count all pending verifications."""
        row = self._db.execute("SELECT COUNT(*) as cnt FROM pending_verifications").fetchone()
        return row["cnt"]


registry_store = RegistryStore()
