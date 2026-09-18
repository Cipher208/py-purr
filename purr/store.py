"""PURR Store — core key-value store with SQLite backend.

Redis-like operations on SQLite with WAL mode, atomic writes,
and thread-safe connections.
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class Store:
    """Thread-safe key-value store backed by SQLite WAL."""

    def __init__(self, db_path: str | Path = "purr.db") -> None:
        self._db_path = Path(db_path)
        self._local = threading.local()
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(str(self._db_path))
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.execute("PRAGMA synchronous=NORMAL")
            # Explicit writer-wait contract: do not rely on the driver default.
            self._local.conn.execute("PRAGMA busy_timeout=5000")
            self._local.conn.row_factory = sqlite3.Row
        return self._local.conn

    def _init_db(self) -> None:
        conn = self._get_conn()
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS kv (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                type TEXT NOT NULL DEFAULT 'string',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS kv_meta (
                key TEXT PRIMARY KEY,
                expires_at TEXT,
                FOREIGN KEY (key) REFERENCES kv(key)
            );
            """
        )
        conn.commit()

    def set(self, key: str, value: Any, ttl: float | None = None) -> bool:
        """Set a key-value pair. Returns True if new, False if updated."""
        conn = self._get_conn()
        now = datetime.now(UTC).isoformat()
        value_json = json.dumps(value)
        value_type = type(value).__name__

        existing = conn.execute("SELECT key FROM kv WHERE key = ?", (key,)).fetchone()

        conn.execute(
            """
            INSERT OR REPLACE INTO kv (key, value, type, created_at, updated_at)
            VALUES (?, ?, ?, COALESCE((SELECT created_at FROM kv WHERE key = ?), ?), ?)
            """,
            (key, value_json, value_type, key, now, now),
        )

        if ttl is not None:
            expires_at = datetime.now(UTC).timestamp() + ttl
            expires_str = datetime.fromtimestamp(expires_at, tz=UTC).isoformat()
            conn.execute(
                "INSERT OR REPLACE INTO kv_meta (key, expires_at) VALUES (?, ?)",
                (key, expires_str),
            )
        else:
            conn.execute("DELETE FROM kv_meta WHERE key = ?", (key,))

        conn.commit()
        return existing is None

    def get(self, key: str) -> Any | None:
        """Get value by key. Returns None if not found or expired."""
        conn = self._get_conn()

        meta = conn.execute("SELECT expires_at FROM kv_meta WHERE key = ?", (key,)).fetchone()
        if meta and meta["expires_at"]:
            expires_at = datetime.fromisoformat(meta["expires_at"])
            if datetime.now(UTC) > expires_at:
                self.delete(key)
                return None

        row = conn.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
        if row is None:
            return None
        return json.loads(row["value"])

    def delete(self, key: str) -> bool:
        """Delete a key. Returns True if key existed."""
        conn = self._get_conn()
        cur = conn.execute("DELETE FROM kv WHERE key = ?", (key,))
        conn.execute("DELETE FROM kv_meta WHERE key = ?", (key,))
        conn.commit()
        return cur.rowcount > 0

    def exists(self, key: str) -> bool:
        """Check if key exists (and is not expired)."""
        return self.get(key) is not None

    def keys(self, pattern: str = "*") -> list[str]:
        """List all keys. Pattern matching with * wildcard."""
        conn = self._get_conn()
        if pattern == "*":
            rows = conn.execute("SELECT key FROM kv").fetchall()
        else:
            sql_pattern = pattern.replace("\\", "\\\\")
            sql_pattern = sql_pattern.replace("%", "\\%").replace("_", "\\_")
            sql_pattern = sql_pattern.replace("*", "%")
            rows = conn.execute(
                "SELECT key FROM kv WHERE key LIKE ? ESCAPE '\\'", (sql_pattern,)
            ).fetchall()
        return [row["key"] for row in rows]

    def ttl(self, key: str) -> float | None:
        """Get TTL in seconds. Returns None if no expiry, -1 if expired."""
        conn = self._get_conn()
        meta = conn.execute("SELECT expires_at FROM kv_meta WHERE key = ?", (key,)).fetchone()
        if not meta or not meta["expires_at"]:
            return None
        expires_at = datetime.fromisoformat(meta["expires_at"])
        remaining = (expires_at - datetime.now(UTC)).total_seconds()
        return max(remaining, -1)

    def expire(self, key: str, ttl: float) -> bool:
        """Set expiry on existing key."""
        conn = self._get_conn()
        row = conn.execute("SELECT key FROM kv WHERE key = ?", (key,)).fetchone()
        if not row:
            return False
        expires_at = datetime.now(UTC).timestamp() + ttl
        expires_str = datetime.fromtimestamp(expires_at, tz=UTC).isoformat()
        conn.execute(
            "INSERT OR REPLACE INTO kv_meta (key, expires_at) VALUES (?, ?)",
            (key, expires_str),
        )
        conn.commit()
        return True

    def incr(self, key: str, amount: int = 1) -> int:
        """Increment a numeric value. Creates with 0 if not exists."""
        conn = self._get_conn()
        row = conn.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
        if row:
            current = json.loads(row["value"])
            if not isinstance(current, (int, float)):
                raise TypeError(f"Cannot increment non-numeric value: {key}")
            new_val = current + amount if isinstance(current, float) else int(current) + amount
        else:
            new_val = amount

        self.set(key, new_val)
        return new_val

    def decr(self, key: str, amount: int = 1) -> int:
        """Decrement a numeric value."""
        return self.incr(key, -amount)

    def mset(self, mapping: dict[str, Any]) -> None:
        """Set multiple keys atomically."""
        conn = self._get_conn()
        now = datetime.now(UTC).isoformat()
        for key, value in mapping.items():
            value_json = json.dumps(value)
            value_type = type(value).__name__
            conn.execute(
                """
                INSERT OR REPLACE INTO kv (key, value, type, created_at, updated_at)
                VALUES (?, ?, ?, COALESCE((SELECT created_at FROM kv WHERE key = ?), ?), ?)
                """,
                (key, value_json, value_type, key, now, now),
            )
        conn.commit()

    def mget(self, keys: list[str]) -> list[Any | None]:
        """Get multiple values."""
        return [self.get(key) for key in keys]

    def sweep(self) -> int:
        """Delete expired keys. Returns count of removed keys."""
        conn = self._get_conn()
        now = datetime.now(UTC).isoformat()
        cur = conn.execute(
            "SELECT key FROM kv_meta WHERE expires_at IS NOT NULL AND expires_at <= ?",
            (now,),
        )
        dead = [row["key"] for row in cur.fetchall()]
        for key in dead:
            conn.execute("DELETE FROM kv WHERE key = ?", (key,))
            conn.execute("DELETE FROM kv_meta WHERE key = ?", (key,))
        conn.commit()
        return len(dead)

    def flush(self) -> int:
        """Delete all keys. Returns count of deleted keys."""
        conn = self._get_conn()
        count = conn.execute("SELECT COUNT(*) FROM kv").fetchone()[0]
        conn.execute("DELETE FROM kv")
        conn.execute("DELETE FROM kv_meta")
        conn.commit()
        return count

    def size(self) -> int:
        """Return number of keys."""
        conn = self._get_conn()
        return conn.execute("SELECT COUNT(*) FROM kv").fetchone()[0]

    def close(self) -> None:
        """Close the connection for this thread."""
        if hasattr(self._local, "conn") and self._local.conn is not None:
            with contextlib.suppress(Exception):
                self._local.conn.close()
            self._local.conn = None
