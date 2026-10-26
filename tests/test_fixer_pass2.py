"""Fixer tests, заход 2: event_stream.py (P1-5, P2 index, batch) and event.py (P1-7)."""

import asyncio
import sqlite3
from datetime import UTC, datetime

import pytest

from purr import Event, EventBus, EventType
from purr.event_stream import EventStream


def _event(event_id: str | None = None, topic: str = "t1", payload: dict | None = None) -> Event:
    kwargs: dict = {"type": EventType.SYSTEM, "topic": topic}
    if payload is not None:
        kwargs["payload"] = payload
    ev = Event(**kwargs)
    if event_id is not None:
        ev.id = event_id
    return ev


# ---------------- Fix 1: P1-5 ----------------


class TestAppendIdempotentReject:
    def test_append_same_id_rejected(self, tmp_path):
        stream = EventStream(tmp_path / "ev.db")
        first = _event(event_id="fixed-id-1", payload={"n": 1})
        stream.append(first)

        with pytest.raises(Exception, match="duplicate event id"):
            stream.append(_event(event_id="fixed-id-1", payload={"n": 999}))

        events, _ = stream.read()
        assert len(events) == 1
        assert events[0].payload == {"n": 1}
        stream.close()

    def test_set_cursor_overwrite_is_contract(self, tmp_path):
        """Cursor rows are mutable by design: set_cursor overwrites (INSERT OR REPLACE).

        This test pins that contract — if it ever fails, cursor semantics changed.
        """
        stream = EventStream(tmp_path / "ev.db")
        e1, e2 = _event(event_id="c1"), _event(event_id="c2")
        stream.append(e1)
        stream.append(e2)

        stream.set_cursor("consumer-a", e1.id)
        assert stream.get_cursor("consumer-a") == e1.id
        stream.set_cursor("consumer-a", e2.id)
        assert stream.get_cursor("consumer-a") == e2.id
        stream.close()


# ---------------- Fix 2: migration v2 index ----------------


class TestMigrationV2:
    def test_migration_v2_creates_topic_ts_index(self, tmp_path):
        stream = EventStream(tmp_path / "ev.db")
        conn = stream._get_conn()
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 2

        cols = [
            name
            for _, name in sorted(
                (r["seqno"], r["name"])
                for r in conn.execute("PRAGMA index_info('idx_events_topic_ts')").fetchall()
            )
        ]
        assert cols == ["topic", "timestamp"]

        # EQP: topic+cursor read uses the index, no TEMP B-TREE
        e1 = _event(event_id="m1", topic="t1")
        stream.append(e1)
        plan = conn.execute(
            "EXPLAIN QUERY PLAN SELECT * FROM events WHERE topic = ? "
            "AND (timestamp, rowid) > (SELECT timestamp, rowid FROM events WHERE id = ?) "
            "ORDER BY timestamp ASC, rowid ASC LIMIT 100",
            ("t1", "m1"),
        ).fetchall()
        detail = " | ".join(r["detail"] for r in plan)
        assert "idx_events_topic_ts" in detail
        assert "TEMP B-TREE" not in detail
        stream.close()

    def test_init_db_idempotent(self, tmp_path):
        stream = EventStream(tmp_path / "ev.db")
        stream.close()
        again = EventStream(tmp_path / "ev.db")
        conn = again._get_conn()
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
        names = [
            r["name"]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()
        ]
        assert names.count("idx_events_topic_ts") == 1
        again.close()


# ---------------- Fix 3: append_many ----------------


class TestAppendMany:
    def test_append_many_roundtrip(self, tmp_path):
        stream = EventStream(tmp_path / "ev.db")
        events = [_event(event_id=f"b{i}", payload={"i": i}) for i in range(1000)]
        stream.append_many(events)
        got, _ = stream.read(limit=2000)
        assert len(got) == 1000
        assert [e.id for e in got] == [f"b{i}" for i in range(1000)]
        stream.close()

    def test_append_many_atomic_on_duplicate(self, tmp_path):
        stream = EventStream(tmp_path / "ev.db")
        events = [_event(event_id=f"a{i}") for i in range(10)]
        events.insert(5, _event(event_id="a0"))  # duplicate mid-batch
        with pytest.raises(Exception, match="duplicate event id"):
            stream.append_many(events)
        assert stream.count() == 0
        stream.close()


# ---------------- Fix 4: publish_sync ----------------


class TestPublishSync:
    def test_publish_sync_calls_subscribers(self):
        bus = EventBus()
        got = []
        bus.subscribe("s.topic", lambda e: got.append(e))
        ev = Event(type=EventType.SYSTEM, topic="s.topic")
        bus.publish_sync(ev)
        assert got == [ev]

    def test_publish_sync_async_handler_no_loop(self):
        bus = EventBus()
        got = []

        async def handler(event: Event):
            got.append(event)

        bus.subscribe("s.topic", handler)
        ev = Event(type=EventType.SYSTEM, topic="s.topic")
        bus.publish_sync(ev)
        assert got == [ev]

    def test_publish_sync_async_in_loop_rejected(self):
        bus = EventBus()

        async def handler(event: Event):
            pass

        bus.subscribe("s.topic", handler)
        with pytest.raises(RuntimeError, match="await bus.publish"):

            async def inside():
                bus.publish_sync(Event(type=EventType.SYSTEM, topic="s.topic"))

            asyncio.run(inside())


# ---------------- Fix 5: rejected duplicate must not leak a transaction ----------------


class TestAppendDuplicateRollsBack:
    def test_append_duplicate_does_not_leak_transaction(self, tmp_path):
        """A rejected duplicate append must leave no open write transaction.

        The failed INSERT otherwise keeps a RESERVED lock on the whole
        database file until close(), so every other writer (other threads,
        other engines, fresh connections) blocks on "database is locked".
        """
        db = tmp_path / "ev.db"
        stream = EventStream(db)
        stream.append(_event(event_id="dup"))

        with pytest.raises(ValueError, match="duplicate event id"):
            stream.append(_event(event_id="dup"))

        # no implicit transaction left behind on the stream's connection
        assert stream._get_conn().in_transaction is False

        # and the file is immediately writable from a fresh connection
        other = sqlite3.connect(str(db), timeout=0.5)
        try:
            other.execute(
                "INSERT INTO events (id, type, topic, timestamp) VALUES (?, ?, ?, ?)",
                ("fresh-id", EventType.SYSTEM.value, "t1", datetime.now(UTC).isoformat()),
            )
            other.commit()
        finally:
            other.close()
        stream.close()
