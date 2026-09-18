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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .backend import SQLiteBackend
from .event import Event, EventType


class EventStream(SQLiteBackend):
    """Persistent event stream with cursors.

    Instance isolation contract: each instance holds its own connection.
    Cursor reads order by (timestamp, rowid); call close() when done.
    """

    def __init__(self, db_path: str | Path = "events.db") -> None:
        super().__init__(db_path)

    def _init_db(self) -> None:
        conn = self._get_conn()
        conn.executescript(
            """
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
            """
        )
        conn.commit()

    def append(self, event: Event) -> None:
        """Append an event to the stream."""
        conn = self._get_conn()
        conn.execute(
            """
            INSERT OR REPLACE INTO events
            (id, type, topic, payload, correlation_id, timestamp, version, source, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.id,
                event.type.value,
                event.topic,
                json.dumps(event.payload),
                event.correlation_id,
                event.timestamp.isoformat(),
                event.version,
                event.source,
                json.dumps(event.metadata),
            ),
        )
        conn.commit()

    def read(
        self,
        cursor: str | None = None,
        topic: str | None = None,
        limit: int = 100,
    ) -> tuple[list[Event], str]:
        """Read events from the stream.

        Args:
            cursor: Start after this event ID (for incremental reads)
            topic: Filter by topic
            limit: Max events to return

        Returns:
            Tuple of (events, last_event_id)
        """
        conn = self._get_conn()
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
        last_id = events[-1].id if events else cursor or ""
        return events, last_id

    def get_cursor(self, name: str) -> str | None:
        """Get cursor position."""
        conn = self._get_conn()
        row = conn.execute("SELECT last_event_id FROM cursors WHERE name = ?", (name,)).fetchone()
        return row["last_event_id"] if row else None

    def set_cursor(self, name: str, event_id: str) -> None:
        """Set cursor position."""
        conn = self._get_conn()
        conn.execute(
            """
            INSERT OR REPLACE INTO cursors (name, last_event_id, updated_at)
            VALUES (?, ?, ?)
            """,
            (name, event_id, datetime.now(UTC).isoformat()),
        )
        conn.commit()

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

    def clear(self) -> None:
        """Clear all events and cursors."""
        conn = self._get_conn()
        conn.execute("DELETE FROM events")
        conn.execute("DELETE FROM cursors")
        conn.commit()

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
