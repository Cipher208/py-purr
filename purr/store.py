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


class Store(SQLiteBackend):
    """Thread-safe key-value store backed by SQLite WAL.

    Instance isolation contract: each instance holds its own connection.
    Multiple instances may share one file safely; call close() when done.
    """

    def __init__(self, db_path: str | Path = "purr.db", journal: EventStream | None = None) -> None:
        """Open the store, optionally journaling every mutation.

        The journal must live in the same file as the data. A journal on
        another file is rejected here, at start-up, instead of being accepted
        and silently drifting: two files cannot share one transaction, so the
        event could be lost after the data was already committed.
        """
        if journal is not None and journal.db_path.resolve() != Path(db_path).resolve():
            raise ValueError(
                "the journal must live in the same file as the data: "
                f"journal={journal.db_path} data={db_path}. "
                "The two-file mode was removed because it is not atomic — an "
                "event could be lost after the data was committed, with nothing "
                "left behind to report the gap. Pass EventStream(db_path) built "
                "on the store's own file, or no journal at all."
            )
        self._journal = journal
        super().__init__(db_path)

    @property
    def _in_transaction(self) -> bool:
        """Per-thread transaction flag (connections are per-thread too)."""
        return getattr(self._local, "in_txn", False)

    @_in_transaction.setter
    def _in_transaction(self, value: bool) -> None:
        self._local.in_txn = value

    def _journal_emit(self, payload: dict[str, Any]) -> None:
        """Insert the mutation event in the caller's transaction (no commit).

        The event shares the data's transaction, so both are committed or
        rolled back together and no buffer is needed. A failing insert
        therefore rolls the data back — the journal is no longer a secondary
        artifact that may lag behind the commit.
        """
        if self._journal is None:
            return
        self._journal.insert_in(
            self._get_conn(), Event(type=EventType.STORE, topic="store", payload=payload)
        )

    def _commit(self) -> None:
        """Commit unless inside an explicit transaction() block."""
        if not self._in_transaction:
            self._get_conn().commit()

    def _rollback_failed_write(self) -> None:
        """Undo a partly applied mutation, unless transaction() owns it.

        Inside transaction() the partial rows belong to the caller's atomic
        block: the context manager rolls back (and takes the journal events
        with it) itself, so rolling back here would hide writes the caller may
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
        Journal events are written inside this transaction, not flushed after
        it, so they are committed or rolled back exactly like the data: a
        failure while writing one rolls the whole block back instead of
        looking like a commit with a gap in the journal.
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
            raise
        finally:
            self._in_transaction = False

    def _init_db(self) -> None:
        self.run_migrations()
        if self._journal is not None:
            # The events table has to exist in this file: the event insert runs
            # on this connection, inside this connection's transaction.
            self._journal.run_migrations()

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

            self._journal_emit({"op": "set", "key": key, "value": value})
            self._commit()
        except Exception:
            self._rollback_failed_write()
            raise

        return created

    def get(self, key: str) -> Any | None:
        """Get value by key. Returns None if not found or expired.

        An expired key is answered as missing but not removed: reading does not
        write, so the row and the journal stay untouched. Physical cleanup
        belongs to sweep()/maintain().
        """
        conn = self._get_conn()

        meta = conn.execute("SELECT expires_at FROM kv_meta WHERE key = ?", (key,)).fetchone()
        if meta and meta["expires_at"]:
            expires_at = datetime.fromisoformat(meta["expires_at"])
            if datetime.now(UTC) > expires_at:
                return None

        row = conn.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
        if row is None:
            return None
        return json.loads(row["value"])

    def delete(self, key: str) -> bool:
        """Delete a key. Returns True if key existed.

        kv_meta goes first: its FK to kv is enforced now, so deleting the
        parent while the child row still exists is a constraint violation.
        The journal event is written inside the same transaction, so rowcount
        is read before the commit — that is the only point where the decision
        "did this delete anything?" still belongs to an open transaction.
        """
        conn = self._get_conn()
        try:
            conn.execute("DELETE FROM kv_meta WHERE key = ?", (key,))
            cur = conn.execute("DELETE FROM kv WHERE key = ?", (key,))
            if cur.rowcount > 0:
                self._journal_emit({"op": "delete", "key": key})
            self._commit()
        except Exception:
            self._rollback_failed_write()
            raise
        return cur.rowcount > 0

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
        try:
            conn.execute(
                "INSERT OR REPLACE INTO kv_meta (key, expires_at) VALUES (?, ?)",
                (key, expires_str),
            )
            self._journal_emit({"op": "expire", "key": key})
            self._commit()
        except Exception:
            self._rollback_failed_write()
            raise
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
            # The event is written before the commit, inside this write
            # transaction: a failing insert rolls the increment back rather
            # than leaving a counter the journal never saw. Inside
            # transaction() there is no commit here at all — the event simply
            # stays in the caller's transaction.
            self._journal_emit({"op": "set", "key": key, "value": new_val})
        except Exception:
            if own_txn:
                conn.rollback()
            raise
        if own_txn:
            conn.commit()
        return new_val

    def decr(self, key: str, amount: int = 1) -> int:
        """Decrement a numeric value."""
        return self.incr(key, -amount)

    def mset(self, mapping: dict[str, Any]) -> None:
        """Set multiple keys atomically.

        Journal events are written in the same transaction as the keys (same
        ordering as set/delete), so a failing event rolls every key of the
        batch back. A failure while serializing or writing any key rolls back
        the keys written so far.
        """
        conn = self._get_conn()
        now = datetime.now(UTC).isoformat()
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
                self._journal_emit({"op": "set", "key": key, "value": value})
            self._commit()
        except Exception:
            self._rollback_failed_write()
            raise

    def mget(self, keys: list[str]) -> list[Any | None]:
        """Get multiple values in two batch queries.

        Before this, mget() was `[self.get(key) for key in keys]` — two
        statements per key (a kv_meta expiry probe plus the value read), so
        1000 keys cost 2000 round-trips. Now one `key IN (...)` query for the
        expired set and one for the values; the answer matches get() exactly,
        expired keys answer None and stay in the table like get() leaves them,
        and the result keeps the order and duplicates of `keys`.
        """
        if not keys:
            return []
        conn = self._get_conn()
        placeholders = ",".join("?" * len(keys))
        now = datetime.now(UTC).isoformat()

        expired = {
            row["key"]
            for row in conn.execute(
                f"SELECT key FROM kv_meta WHERE key IN ({placeholders})"
                " AND expires_at IS NOT NULL AND expires_at <= ?",
                (*keys, now),
            ).fetchall()
        }

        rows = conn.execute(
            f"SELECT key, value FROM kv WHERE key IN ({placeholders})", keys
        ).fetchall()
        values = {row["key"]: json.loads(row["value"]) for row in rows}
        # Masked here, not deleted: the row stays for sweep(), and without the
        # mask the expired value would come back as live.
        return [None if key in expired else values.get(key) for key in keys]

    def sweep(self) -> int:
        """Delete expired keys. Returns count of removed keys.

        Every removal is journalled: a replay of the journal has to reach the
        same state as the database, and a key that disappears from `kv` while
        the journal still shows it alive is a silent divergence.
        """
        conn = self._get_conn()
        now = datetime.now(UTC).isoformat()
        cur = conn.execute(
            "SELECT key FROM kv_meta WHERE expires_at IS NOT NULL AND expires_at <= ?",
            (now,),
        )
        dead = [row["key"] for row in cur.fetchall()]
        try:
            for key in dead:
                conn.execute("DELETE FROM kv_meta WHERE key = ?", (key,))
                conn.execute("DELETE FROM kv WHERE key = ?", (key,))
                self._journal_emit({"op": "delete", "key": key})
            self._commit()
        except Exception:
            self._rollback_failed_write()
            raise
        return len(dead)

    def flush(self) -> int:
        """Delete all keys. Returns count of deleted keys.

        Like `sweep`, every removal is journalled, so the journal can rebuild
        an empty store from the same events the database recorded.
        """
        conn = self._get_conn()
        keys = [row["key"] for row in conn.execute("SELECT key FROM kv").fetchall()]
        try:
            conn.execute("DELETE FROM kv_meta")
            conn.execute("DELETE FROM kv")
            for key in keys:
                self._journal_emit({"op": "delete", "key": key})
            self._commit()
        except Exception:
            self._rollback_failed_write()
            raise
        return len(keys)

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
