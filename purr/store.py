"""PURR Store — core key-value store with SQLite backend.

Redis-like operations on SQLite with WAL mode, atomic writes,
and thread-safe connections.
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .backend import SQLiteBackend
from .event import Event, EventType

if TYPE_CHECKING:
    from .event_stream import EventStream


class JournalFlushError(RuntimeError):
    """The data committed, but some journal events could not be written.

    Raised after the commit, never instead of it: the caller is told that the
    transaction is durable and only the journal is incomplete, so a failed
    flush cannot be mistaken for a rollback.
    """


class Store(SQLiteBackend):
    """Thread-safe key-value store backed by SQLite WAL.

    Instance isolation contract: each instance holds its own connection.
    Multiple instances may share one file safely; call close() when done.
    """

    def __init__(self, db_path: str | Path = "purr.db", journal: EventStream | None = None) -> None:
        self._journal = journal
        super().__init__(db_path)

    @property
    def _in_transaction(self) -> bool:
        """Per-thread transaction flag (connections are per-thread too)."""
        return getattr(self._local, "in_txn", False)

    @_in_transaction.setter
    def _in_transaction(self, value: bool) -> None:
        self._local.in_txn = value

    @property
    def _journal_buffer(self) -> list[dict[str, Any]]:
        """Per-thread journal buffer (matches per-thread connections/txn flag)."""
        if not hasattr(self._local, "journal_buffer"):
            self._local.journal_buffer = []
        return self._local.journal_buffer

    def _journal_emit(self, payload: dict[str, Any]) -> None:
        """Append a mutation event to the journal stream (buffered in txn)."""
        if self._journal is None:
            return
        if self._in_transaction:
            self._journal_buffer.append(payload)
            return
        self._journal.append(Event(type=EventType.STORE, topic="store", payload=payload))

    def _journal_flush(self) -> None:
        """Write buffered mutation events after transaction commit.

        Every event is attempted even if an earlier one fails — one rejected
        event must not silently drop the rest. Partial loss is reported with
        JournalFlushError: the data is committed either way, so this can never
        be presented as a rollback.
        """
        if self._journal is None:
            return
        buffered = list(self._journal_buffer)
        self._journal_buffer.clear()
        failed: list[dict[str, Any]] = []
        last_error: Exception | None = None
        for payload in buffered:
            try:
                self._journal.append(Event(type=EventType.STORE, topic="store", payload=payload))
            except Exception as exc:
                failed.append(payload)
                last_error = exc
        if failed:
            raise JournalFlushError(
                f"transaction committed, but {len(failed)} journal events failed to flush; "
                "data is durable, only the journal is incomplete "
                f"(lost keys: {[p.get('key') for p in failed]})"
            ) from last_error

    def _commit(self) -> None:
        """Commit unless inside an explicit transaction() block."""
        if not self._in_transaction:
            self._get_conn().commit()

    def _rollback_failed_write(self) -> None:
        """Undo a partly applied mutation, unless transaction() owns it.

        Inside transaction() the partial rows belong to the caller's atomic
        block: the context manager rolls back (and drops buffered journal
        events) itself, so rolling back here would hide writes the caller may
        still intend to commit after catching the error.
        """
        if self._in_transaction:
            return
        with contextlib.suppress(sqlite3.Error):
            self._get_conn().rollback()

    @contextlib.contextmanager
    def transaction(self) -> Iterator[Store]:
        """Atomic multi-op block. Commits on clean exit, rolls back on error.

        No nesting. Inner per-op commits are deferred until the block ends.
        Journal events are flushed after the commit, outside the rollback
        path: a flush failure raises JournalFlushError (the data is already
        durable) instead of looking like a rollback.
        """
        if self._in_transaction:
            raise RuntimeError("nested transaction() is not supported")
        conn = self._get_conn()
        self._in_transaction = True
        try:
            conn.execute("BEGIN IMMEDIATE")
        except Exception:
            self._in_transaction = False
            raise
        try:
            yield self
            conn.commit()
        except Exception:
            conn.rollback()
            self._journal_buffer.clear()
            raise
        finally:
            self._in_transaction = False
        self._journal_flush()

    def _init_db(self) -> None:
        self.run_migrations()

    SCHEMA_VERSION = 2
    ENGINE_NAME = "store"
    MIGRATIONS = {
        1: """
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
            """,
        # v2: sweep()/mget() filter on kv_meta.expires_at, which had no index —
        # every expiry pass was a full scan of kv_meta. CREATE INDEX only, so
        # existing databases are upgraded in place (the table is not recreated).
        2: "CREATE INDEX IF NOT EXISTS idx_kv_meta_expires ON kv_meta(expires_at);",
    }

    def set(self, key: str, value: Any, ttl: float | None = None) -> bool:
        """Set a key-value pair. Returns True if new, False if updated.

        One statement when the key is created, two when it is overwritten: the
        `ON CONFLICT DO NOTHING` insert answers "did I create it?" by itself,
        and the overwrite path is a plain UPDATE that never touches
        created_at. Before this, every set() ran an extra
        `SELECT key FROM kv WHERE key = ?` for the flag and a correlated
        `COALESCE((SELECT created_at ...))` inside the INSERT — three index
        lookups per write.

        A single UPSERT with `RETURNING created_at` compared against `now`
        would be one statement fewer, but it cannot tell a create from an
        overwrite here: datetime.now() has a ~16 ms tick on Windows (2000
        consecutive calls yield 2-3 distinct values), and a rewrite of the
        same key happens microseconds later, so the timestamps are equal and
        the write would be reported as a create.

        A failure part-way through (unserializable value, ttl overflow) rolls
        the partial write back: no half-applied row survives to be committed
        by the next unrelated write.
        """
        conn = self._get_conn()
        now = datetime.now(UTC).isoformat()
        value_json = json.dumps(value)
        value_type = type(value).__name__

        try:
            inserted = conn.execute(
                """
                INSERT INTO kv (key, value, type, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(key) DO NOTHING
                RETURNING key
                """,
                (key, value_json, value_type, now, now),
            ).fetchone()
            created = inserted is not None
            if not created:
                conn.execute(
                    "UPDATE kv SET value = ?, type = ?, updated_at = ? WHERE key = ?",
                    (value_json, value_type, now, key),
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

            self._commit()
        except Exception:
            self._rollback_failed_write()
            raise

        self._journal_emit({"op": "set", "key": key, "value": value})
        return created

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
        """Delete a key. Returns True if key existed.

        kv_meta goes first: its FK to kv is enforced now, so deleting the
        parent while the child row still exists is a constraint violation.
        """
        conn = self._get_conn()
        try:
            conn.execute("DELETE FROM kv_meta WHERE key = ?", (key,))
            cur = conn.execute("DELETE FROM kv WHERE key = ?", (key,))
            self._commit()
        except Exception:
            self._rollback_failed_write()
            raise
        deleted = cur.rowcount > 0
        if deleted:
            self._journal_emit({"op": "delete", "key": key})
        return deleted

    def exists(self, key: str) -> bool:
        """Check if key exists (and is not expired)."""
        return self.get(key) is not None

    def keys(self, pattern: str = "*") -> list[str]:
        """List keys matching a pattern. Pattern matching with * wildcard.

        Case-sensitive, like Redis KEYS: the connection runs with
        `PRAGMA case_sensitive_like=ON`, so `USER:*` does not match `user:1`.
        """
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
        self._commit()
        self._journal_emit({"op": "expire", "key": key})
        return True

    def incr(self, key: str, amount: int = 1) -> int:
        """Increment a numeric value atomically. Creates with amount if not exists.

        Expired keys are not resurrected: incrementing an expired or missing
        key starts from 0 (Redis INCR semantics). TTL of a live key is kept.
        """
        conn = self._get_conn()
        now = datetime.now(UTC).isoformat()
        own_txn = not self._in_transaction
        # A previous statement may have left an implicit transaction open on
        # this connection (a raw write run through _get_conn(), for instance).
        # BEGIN on top of it raises "cannot start a transaction within a
        # transaction"; the implicit one already gives us the write lock, so
        # reuse it.
        if own_txn and not conn.in_transaction:
            conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
            current: Any = None
            if row is not None:
                meta = conn.execute(
                    "SELECT expires_at FROM kv_meta WHERE key = ?", (key,)
                ).fetchone()
                if meta and meta["expires_at"]:
                    expires_at = datetime.fromisoformat(meta["expires_at"])
                    if datetime.now(UTC) > expires_at:
                        conn.execute("DELETE FROM kv_meta WHERE key = ?", (key,))
                        conn.execute("DELETE FROM kv WHERE key = ?", (key,))
                        row = None
            if row is not None:
                current = json.loads(row["value"])
                if not isinstance(current, (int, float)):
                    raise TypeError(f"Cannot increment non-numeric value: {key}")
                new_val = current + amount if isinstance(current, float) else int(current) + amount
                conn.execute(
                    "UPDATE kv SET value = ?, updated_at = ? WHERE key = ?",
                    (json.dumps(new_val), now, key),
                )
            else:
                new_val = amount
                conn.execute(
                    "INSERT OR REPLACE INTO kv (key, value, type, created_at, updated_at)"
                    " VALUES (?, ?, 'int', ?, ?)",
                    (key, json.dumps(amount), now, now),
                )
            # kv_meta untouched for live keys: TTL preserved (P1-4).
        except Exception:
            if own_txn:
                conn.rollback()
            raise
        if own_txn:
            conn.commit()
        # Emitted after the commit, like set/mset: a journal subscriber must
        # never see the event before the data (and on a shared file the emit
        # would otherwise block on this connection's own RESERVED lock).
        # Inside transaction() the event is buffered until the block commits.
        self._journal_emit({"op": "set", "key": key, "value": new_val})
        return new_val

    def decr(self, key: str, amount: int = 1) -> int:
        """Decrement a numeric value."""
        return self.incr(key, -amount)

    def mset(self, mapping: dict[str, Any]) -> None:
        """Set multiple keys atomically.

        Journal events are emitted after the commit (same ordering as
        set/delete), so journal consumers never observe uncommitted data.
        A failure while serializing or writing any key rolls back the keys
        written so far.
        """
        conn = self._get_conn()
        now = datetime.now(UTC).isoformat()
        journal_payloads: list[dict[str, Any]] = []
        try:
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
                journal_payloads.append({"op": "set", "key": key, "value": value})
            self._commit()
        except Exception:
            self._rollback_failed_write()
            raise
        for payload in journal_payloads:
            self._journal_emit(payload)

    def mget(self, keys: list[str]) -> list[Any | None]:
        """Get multiple values in two batch queries.

        Before this, mget() was `[self.get(key) for key in keys]` — two
        statements per key (a kv_meta expiry probe plus the value read), so
        1000 keys cost 2000 round-trips. Now one `key IN (...)` query for the
        expired set and one for the values; the answer matches get() exactly,
        expired keys are deleted like get() does (journal event included), and
        the result keeps the order and duplicates of `keys`.
        """
        if not keys:
            return []
        conn = self._get_conn()
        placeholders = ",".join("?" * len(keys))
        now = datetime.now(UTC).isoformat()

        expired = [
            row["key"]
            for row in conn.execute(
                f"SELECT key FROM kv_meta WHERE key IN ({placeholders})"
                " AND expires_at IS NOT NULL AND expires_at <= ?",
                (*keys, now),
            ).fetchall()
        ]
        for key in dict.fromkeys(expired):
            self.delete(key)

        rows = conn.execute(
            f"SELECT key, value FROM kv WHERE key IN ({placeholders})", keys
        ).fetchall()
        values = {row["key"]: json.loads(row["value"]) for row in rows}
        return [values.get(key) for key in keys]

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
            conn.execute("DELETE FROM kv_meta WHERE key = ?", (key,))
            conn.execute("DELETE FROM kv WHERE key = ?", (key,))
        self._commit()
        return len(dead)

    def flush(self) -> int:
        """Delete all keys. Returns count of deleted keys."""
        conn = self._get_conn()
        count = conn.execute("SELECT COUNT(*) FROM kv").fetchone()[0]
        conn.execute("DELETE FROM kv_meta")
        conn.execute("DELETE FROM kv")
        self._commit()
        return count

    def size(self) -> int:
        """Return number of keys."""
        conn = self._get_conn()
        return conn.execute("SELECT COUNT(*) FROM kv").fetchone()[0]

    def maintain(self) -> dict[str, Any]:
        """Host-driven maintenance: sweep, checkpoint, verify. Returns report."""
        swept = self.sweep()
        report: dict[str, Any] = {
            "swept": swept,
            "keys": self.size(),
            "checkpoint": self.checkpoint(),
            "integrity": self.integrity(),
        }
        report.update(self.db_stats())
        return report
