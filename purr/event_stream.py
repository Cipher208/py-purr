"""PURR EventStream — persistent event store with cursors.

Like Redis Streams but on SQLite. Supports:
- Append events
- Read with cursor (incremental)
- Named cursors for consumers
- Topic filtering
- WAL mode for concurrency
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .backend import SQLiteBackend
from .event import Event, EventType


class EventStream(SQLiteBackend):
    """Persistent event stream with cursors.

    Instance isolation contract: each instance holds its own connection.
    Cursor reads order by (timestamp, rowid); call close() when done.
    """

    def __init__(
        self,
        db_path: str | Path = "events.db",
        max_events: int | None = None,
        max_age_seconds: float | None = None,
    ) -> None:
        """Open (or create) the stream.

        Retention limits are validated up front, before the database is
        touched:

        - ``max_events`` must be None or an int >= 1. ``0`` is rejected:
          pruning to zero deletes the whole stream. ``-1`` is rejected too:
          SQLite turns ``LIMIT -1`` into "no limit", so retention would be
          silently disabled. A float (``2.9``) reaches SQLite as a datatype
          mismatch and fails inside maintain(), and ``"2"`` would be coerced
          silently — neither is accepted.
        - ``max_age_seconds`` must be None or an int/float > 0.

        bool is rejected for both even though it is an int subclass: True
        and False as a retention limit are always a mistake.
        """
        if max_events is not None and (
            isinstance(max_events, bool) or not isinstance(max_events, int) or max_events < 1
        ):
            raise ValueError("max_events must be a positive int or None")
        if max_age_seconds is not None and (
            isinstance(max_age_seconds, bool)
            or not isinstance(max_age_seconds, int | float)
            or max_age_seconds <= 0
        ):
            raise ValueError("max_age_seconds must be a positive number or None")
        super().__init__(db_path)
        self._max_events = max_events
        self._max_age_seconds = max_age_seconds

    def _init_db(self) -> None:
        self.run_migrations()

    SCHEMA_VERSION = 2
    ENGINE_NAME = "event_stream"
    MIGRATIONS = {
        1: """
            CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                topic TEXT NOT NULL,
                payload TEXT NOT NULL DEFAULT '{}',
                correlation_id TEXT,
                timestamp TEXT NOT NULL,
                version INTEGER NOT NULL DEFAULT 1,
                source TEXT NOT NULL DEFAULT '',
                metadata TEXT NOT NULL DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS idx_events_topic ON events(topic);
            CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);
            CREATE INDEX IF NOT EXISTS idx_events_correlation ON events(correlation_id);

            CREATE TABLE IF NOT EXISTS cursors (
                name TEXT PRIMARY KEY,
                last_event_id TEXT,
                updated_at TEXT NOT NULL
            );
            """,
        # v2: composite index removes the TEMP B-TREE sort from
        # read(cursor, topic) — measured 20.10 → 0.74 ms/op on 100k events.
        2: "CREATE INDEX IF NOT EXISTS idx_events_topic_ts ON events(topic, timestamp);",
    }

    def _validate_timestamp(self, event: Event) -> None:
        """Reject events stamped far in the future.

        Retention compares the stored timestamp as TEXT against a UTC cutoff,
        so an event dated year 9999 never falls below it and can never be
        pruned. One day of slack tolerates clock skew between producers.
        """
        limit = datetime.now(UTC) + timedelta(days=1)
        if event.timestamp.astimezone(UTC) > limit:
            raise ValueError(
                f"event timestamp is more than 1 day in the future: {event.timestamp.isoformat()}"
            )

    def append(self, event: Event) -> None:
        """Append an event to the stream.

        The stream is append-only: appending an event whose id already exists
        raises ValueError("duplicate event id: ...") and leaves the original
        event untouched. A timestamp more than one day in the future is
        rejected up front.
        """
        self._validate_timestamp(event)
        conn = self._get_conn()
        try:
            self._insert(conn, event)
        except sqlite3.IntegrityError as exc:
            # The failed INSERT already opened an implicit transaction; leaving
            # it open holds a RESERVED lock on the whole database file, so every
            # other writer blocks until close(). Same as append_many().
            conn.rollback()
            raise ValueError(f"duplicate event id: {event.id}") from exc
        conn.commit()

    def append_many(self, events: list[Event]) -> None:
        """Append multiple events in a single transaction (one commit at the end).

        Atomic: if any event id already exists in the stream (or duplicates
        another id in the batch), ValueError("duplicate event id: ...") is
        raised and the whole batch is rolled back — no event is written.
        Timestamps more than one day in the future are rejected before any
        insert is attempted.
        """
        for event in events:
            self._validate_timestamp(event)
        conn = self._get_conn()
        try:
            for event in events:
                self._insert(conn, event)
        except sqlite3.IntegrityError as exc:
            conn.rollback()
            raise ValueError(f"duplicate event id (batch rolled back): {event.id}") from exc
        except Exception:
            # Any other failure (a payload that is not JSON serializable,
            # for instance) must roll back too: otherwise the events already
            # inserted stay in the open transaction and the next unrelated
            # append() commits them, resurrecting the rejected batch.
            conn.rollback()
            raise
        conn.commit()

    def _insert(self, conn: sqlite3.Connection, event: Event) -> None:
        """Shared INSERT used by append/append_many (no commit here).

        timestamps are stored normalized to UTC: read() orders and retention
        filters compare the TEXT column, so a non-UTC offset
        ("...T11:13-05:00") would sort before a UTC "now" and be pruned as
        old while a future date would never be pruned.
        """
        conn.execute(
            """
            INSERT INTO events
            (id, type, topic, payload, correlation_id, timestamp, version, source, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.id,
                event.type.value,
                event.topic,
                json.dumps(event.payload),
                event.correlation_id,
                event.timestamp.astimezone(UTC).isoformat(),
                event.version,
                event.source,
                json.dumps(event.metadata),
            ),
        )

    def read(
        self,
        cursor: str | None = None,
        topic: str | None = None,
        limit: int = 100,
    ) -> tuple[list[Event], str | None]:
        """Read events from the stream.

        Args:
            cursor: Start after this event ID (for incremental reads).
                None (default) reads from the beginning of the stream.
                If cursor is given and the referenced event does not exist,
                ValueError is raised — a missing cursor id can never match
                any event, so reading would silently return nothing forever.
            topic: Filter by topic
            limit: Max events to return

        Returns:
            Tuple of (events, last_event_id). last_event_id is None when
            there is nothing new — do NOT write it back, guard the write-back
            with `if last_id:`. set_cursor(name, None) is rejected precisely
            because a NULL cursor reads from the beginning of the stream and
            would replay every event.
        """
        conn = self._get_conn()

        if cursor:
            row = conn.execute("SELECT 1 FROM events WHERE id = ?", (cursor,)).fetchone()
            if row is None:
                raise ValueError(
                    f"cursor references missing event id: {cursor} "
                    "(retention may have pruned it; call reset_cursor(name) "
                    "to restart from the beginning)"
                )

        query = "SELECT * FROM events"
        params: list[Any] = []
        conditions: list[str] = []

        if cursor:
            conditions.append(
                "(timestamp, rowid) > (SELECT timestamp, rowid FROM events WHERE id = ?)"
            )
            params.append(cursor)

        if topic:
            conditions.append("topic = ?")
            params.append(topic)

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += " ORDER BY timestamp ASC, rowid ASC LIMIT ?"
        params.append(limit)

        rows = conn.execute(query, params).fetchall()
        events = [self._row_to_event(row) for row in rows]
        last_id = events[-1].id if events else None
        return events, last_id

    def get_cursor(self, name: str) -> str | None:
        """Get cursor position."""
        conn = self._get_conn()
        row = conn.execute("SELECT last_event_id FROM cursors WHERE name = ?", (name,)).fetchone()
        return row["last_event_id"] if row else None

    def set_cursor(self, name: str, event_id: str) -> None:
        """Set cursor position.

        event_id must be a real event id: an empty id (None or "") would be
        stored as NULL, and read(cursor=None) reads from the beginning — so
        far from being a no-op it silently replays the whole stream. Use
        reset_cursor() to clear a cursor on purpose.
        """
        if not event_id:
            raise ValueError(
                "set_cursor requires an event id; use reset_cursor(name) to clear the cursor"
            )
        conn = self._get_conn()
        conn.execute(
            """
            INSERT OR REPLACE INTO cursors (name, last_event_id, updated_at)
            VALUES (?, ?, ?)
            """,
            (name, event_id, datetime.now(UTC).isoformat()),
        )
        conn.commit()

    def reset_cursor(self, name: str) -> bool:
        """Delete a named cursor.

        Call after a cursor was invalidated by retention; the consumer will
        read from the beginning. Returns True if the cursor existed.
        """
        conn = self._get_conn()
        cur = conn.execute("DELETE FROM cursors WHERE name = ?", (name,))
        conn.commit()
        return cur.rowcount > 0

    def count(self, topic: str | None = None) -> int:
        """Count events."""
        conn = self._get_conn()
        if topic:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM events WHERE topic = ?", (topic,)
            ).fetchone()
        else:
            row = conn.execute("SELECT COUNT(*) as cnt FROM events").fetchone()
        return row["cnt"]

    def count_since(self, topic: str | None = None, seconds: float = 3600) -> int:
        """Count events in the trailing window. Compute-on-read by design."""
        from datetime import UTC, datetime, timedelta

        cutoff = (datetime.now(UTC) - timedelta(seconds=seconds)).isoformat()
        conn = self._get_conn()
        if topic:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM events WHERE topic = ? AND timestamp >= ?",
                (topic, cutoff),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM events WHERE timestamp >= ?", (cutoff,)
            ).fetchone()
        return row["cnt"]

    def clear(self) -> None:
        """Clear all events and cursors."""
        conn = self._get_conn()
        conn.execute("DELETE FROM events")
        conn.execute("DELETE FROM cursors")
        conn.commit()

    def maintain(self) -> dict[str, Any]:
        """Host-driven maintenance: checkpoint, verify, optional retention.

        When max_events/max_age_seconds were configured at construction,
        maintain() prunes the log (for max_events it keeps the newest
        events in read order, i.e. by (timestamp, rowid) DESC; for
        max_age_seconds it drops events older than the cutoff). Both limits
        must be positive (max_events >= 1, max_age_seconds > 0): 0 and
        negatives are rejected by __init__, there is no "prune everything"
        mode. Cursors pointing at pruned events are left in place — reading
        with such a cursor now raises ValueError; call reset_cursor(name) to
        drop it and restart that consumer from the beginning. By default
        (no limits) the replay log is never pruned.
        """
        report: dict[str, Any] = {
            "events": self.count(),
            "checkpoint": self.checkpoint(),
            "integrity": self.integrity(),
        }
        if self._max_events is not None or self._max_age_seconds is not None:
            report["pruned_events"] = self._prune()
        report.update(self.db_stats())
        return report

    def _prune(self) -> int:
        conn = self._get_conn()
        pruned = 0
        if self._max_age_seconds is not None:
            cutoff = (datetime.now(UTC) - timedelta(seconds=self._max_age_seconds)).isoformat()
            cur = conn.execute("DELETE FROM events WHERE timestamp < ?", (cutoff,))
            pruned += cur.rowcount
        if self._max_events is not None:
            # Keep the newest events in the same order read() walks them
            # (timestamp ASC, rowid ASC). Ordering by rowid alone would
            # discard the truly newest event when a producer writes out of
            # timestamp order, stranding that consumer's cursor.
            cur = conn.execute(
                """
                DELETE FROM events WHERE id NOT IN (
                    SELECT id FROM events ORDER BY timestamp DESC, rowid DESC LIMIT ?
                )
                """,
                (self._max_events,),
            )
            pruned += cur.rowcount
        # DELETE opens an implicit transaction even when it matches no rows
        # (rowcount 0): committing only "if pruned" left it open, pinning a
        # RESERVED lock on the whole file and blocking every other writer
        # until close(). Commit whenever the connection holds a transaction.
        if conn.in_transaction:
            conn.commit()
        return pruned

    def _row_to_event(self, row: sqlite3.Row) -> Event:
        """Convert a database row to an Event."""
        return Event(
            id=row["id"],
            type=EventType(row["type"]),
            topic=row["topic"],
            payload=json.loads(row["payload"]),
            correlation_id=row["correlation_id"],
            timestamp=datetime.fromisoformat(row["timestamp"]),
            version=row["version"],
            source=row["source"],
            metadata=json.loads(row["metadata"]),
        )
