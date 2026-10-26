"""Tests for PURR EventStream."""

import pytest

from purr import Event, EventStream, EventType


@pytest.fixture
def stream(tmp_path):
    """Create a temporary event stream."""
    return EventStream(tmp_path / "events.db")


class TestEventStream:
    def test_append_and_read(self, stream):
        event = Event(
            type=EventType.SYSTEM,
            topic="test.topic",
            payload={"msg": "hello"},
            version=1,
            source="test_src",
            metadata={"priority": "high"},
        )
        stream.append(event)

        events, last_id = stream.read()
        assert len(events) == 1
        assert events[0].id == event.id
        assert events[0].topic == "test.topic"
        assert events[0].payload == {"msg": "hello"}
        assert events[0].version == 1
        assert events[0].source == "test_src"
        assert events[0].metadata == {"priority": "high"}
        assert last_id == event.id

    def test_filter_by_topic(self, stream):
        e1 = Event(type=EventType.STORE, topic="topic.a", payload={"val": 1})
        e2 = Event(type=EventType.STORE, topic="topic.b", payload={"val": 2})
        stream.append(e1)
        stream.append(e2)

        events_a, _ = stream.read(topic="topic.a")
        assert len(events_a) == 1
        assert events_a[0].id == e1.id

        events_b, _ = stream.read(topic="topic.b")
        assert len(events_b) == 1
        assert events_b[0].id == e2.id

    def test_cursor_tracking(self, stream):
        e1 = Event(type=EventType.STATE, topic="worker", payload={"job": 1})
        e2 = Event(type=EventType.STATE, topic="worker", payload={"job": 2})
        stream.append(e1)
        stream.append(e2)

        stream.set_cursor("consumer_1", e1.id)
        assert stream.get_cursor("consumer_1") == e1.id

        events, last_id = stream.read(cursor=e1.id)
        assert len(events) == 1
        assert events[0].id == e2.id
        assert last_id == e2.id

    def test_cursor_survives_same_timestamp(self, stream):
        from datetime import UTC, datetime

        ts = datetime.now(UTC)
        e1 = Event(type=EventType.STATE, topic="w", payload={"job": 1}, timestamp=ts)
        e2 = Event(type=EventType.STATE, topic="w", payload={"job": 2}, timestamp=ts)
        stream.append(e1)
        stream.append(e2)

        events, _ = stream.read(cursor=e1.id)
        assert [e.id for e in events] == [e2.id]

    def test_count_and_clear(self, stream):
        e1 = Event(type=EventType.SYSTEM, topic="t1", payload={})
        e2 = Event(type=EventType.SYSTEM, topic="t2", payload={})
        stream.append(e1)
        stream.append(e2)

        assert stream.count() == 2
        assert stream.count(topic="t1") == 1

        stream.clear()
        assert stream.count() == 0

    def test_count_since_window(self, stream):
        from datetime import UTC, datetime, timedelta

        old = Event(
            type=EventType.SYSTEM,
            topic="err",
            payload={},
            timestamp=datetime.now(UTC) - timedelta(hours=2),
        )
        fresh = Event(type=EventType.SYSTEM, topic="err", payload={})
        other = Event(type=EventType.SYSTEM, topic="ok", payload={})
        stream.append(old)
        stream.append(fresh)
        stream.append(other)

        assert stream.count_since("err", seconds=3600) == 1
        assert stream.count_since(seconds=3600) == 2


class TestCursorSemantics:
    def test_read_missing_cursor_id_raises(self, stream):
        e = Event(type=EventType.SYSTEM, topic="t", payload={})
        stream.append(e)
        with pytest.raises(ValueError, match="cursor references missing event id"):
            stream.read(cursor="nonexistent-id")

    def test_empty_read_returns_none_last_id(self, stream):
        e = Event(type=EventType.SYSTEM, topic="t", payload={})
        stream.append(e)
        events, last_id = stream.read(cursor=e.id)
        assert events == []
        assert last_id is None

    def test_read_from_beginning_without_cursor(self, stream):
        e = Event(type=EventType.SYSTEM, topic="t", payload={})
        stream.append(e)
        events, last_id = stream.read()
        assert [ev.id for ev in events] == [e.id]
        assert last_id == e.id


class TestCursorSemantics:
    def test_read_missing_cursor_id_raises(self, stream):
        e = Event(type=EventType.SYSTEM, topic="t", payload={})
        stream.append(e)
        with pytest.raises(ValueError, match="cursor references missing event id"):
            stream.read(cursor="nonexistent-id")

    def test_empty_read_returns_none_last_id(self, stream):
        e = Event(type=EventType.SYSTEM, topic="t", payload={})
        stream.append(e)
        events, last_id = stream.read(cursor=e.id)
        assert events == []
        assert last_id is None

    def test_read_from_beginning_without_cursor(self, stream):
        e = Event(type=EventType.SYSTEM, topic="t", payload={})
        stream.append(e)
        events, last_id = stream.read()
        assert [ev.id for ev in events] == [e.id]
        assert last_id == e.id


class TestRetention:
    def test_maintain_respects_max_events(self, tmp_path):
        stream = EventStream(tmp_path / "ev.db", max_events=3)
        events = [Event(type=EventType.SYSTEM, topic="t", payload={"i": i}) for i in range(6)]
        stream.append_many(events)
        report = stream.maintain()
        assert report["pruned_events"] == 3
        assert stream.count() == 3
        remaining = stream.read(limit=10)[0]
        assert [e.payload["i"] for e in remaining] == [3, 4, 5]

    def test_maintain_respects_max_age(self, tmp_path):
        from datetime import UTC, datetime, timedelta

        stream = EventStream(tmp_path / "ev.db", max_age_seconds=3600)
        old = Event(
            type=EventType.SYSTEM, topic="t", payload={}, timestamp=datetime.now(UTC) - timedelta(hours=2)
        )
        fresh = Event(type=EventType.SYSTEM, topic="t", payload={})
        stream.append_many([old, fresh])
        report = stream.maintain()
        assert report["pruned_events"] == 1
        assert stream.count() == 1
        assert stream.read()[0][0].id == fresh.id

    def test_default_no_retention(self, stream):
        events = [Event(type=EventType.SYSTEM, topic="t", payload={}) for _ in range(5)]
        stream.append_many(events)
        report = stream.maintain()
        assert "pruned_events" not in report
        assert stream.count() == 5

    def test_prune_keeps_newest_by_read_order(self, tmp_path):
        """Retention must keep what read() considers newest: (timestamp, rowid)."""
        from datetime import UTC, datetime, timedelta

        stream = EventStream(tmp_path / "ev.db", max_events=1)
        now = datetime.now(UTC)
        newer = Event(type=EventType.SYSTEM, topic="t", payload={"k": "newer"}, timestamp=now)
        older = Event(
            type=EventType.SYSTEM,
            topic="t",
            payload={"k": "older"},
            timestamp=now - timedelta(days=1),
        )
        # Producer writes out of timestamp order (newer first).
        stream.append(newer)
        stream.append(older)
        stream.maintain()

        remaining = stream.read(limit=10)[0]
        assert [e.payload["k"] for e in remaining] == ["newer"]
        # A consumer whose cursor sat on the newest event keeps working.
        events, last_id = stream.read(cursor=newer.id)
        assert events == []
        assert last_id is None

    def test_reset_cursor_after_prune(self, tmp_path):
        stream = EventStream(tmp_path / "ev.db", max_events=3)
        events = [Event(type=EventType.SYSTEM, topic="t", payload={"i": i}) for i in range(5)]
        stream.append_many(events)
        stream.maintain()

        pruned_id = events[0].id
        assert [e.id for e in stream.read(limit=10)[0]] == [e.id for e in events[2:]]

        stream.set_cursor("c", pruned_id)
        with pytest.raises(ValueError):
            stream.read(cursor=stream.get_cursor("c"))

        assert stream.reset_cursor("c") is True
        assert stream.get_cursor("c") is None

        restarted = stream.read()[0]
        assert [e.id for e in restarted] == [e.id for e in events[2:]]

        assert stream.reset_cursor("c") is False

    def test_read_missing_cursor_message_mentions_reset(self, stream):
        e = Event(type=EventType.SYSTEM, topic="t", payload={})
        stream.append(e)
        with pytest.raises(ValueError) as excinfo:
            stream.read(cursor="nonexistent-id")
        assert "reset_cursor" in str(excinfo.value)


class TestCursorReplaySafety:
    """A None last_id written back as a cursor silently replays the stream."""

    def test_set_cursor_rejects_none_and_empty(self, stream):
        for bad in (None, ""):
            with pytest.raises(ValueError, match="reset_cursor"):
                stream.set_cursor("c", bad)  # type: ignore[arg-type]

        assert stream.get_cursor("c") is None
        rows = stream._get_conn().execute("SELECT COUNT(*) FROM cursors").fetchone()[0]
        assert rows == 0

    def test_read_annotation_allows_none(self, stream):
        """Pin the documented consumer loop: never write back a None last_id."""
        e1 = Event(type=EventType.SYSTEM, topic="t", payload={})
        stream.append(e1)

        events, last_id = stream.read(cursor=stream.get_cursor("my-consumer"))
        assert [ev.id for ev in events] == [e1.id]
        assert last_id == e1.id
        if last_id:
            stream.set_cursor("my-consumer", last_id)

        # Nothing new: last_id is None — guarded write-back leaves the cursor alone.
        events, last_id = stream.read(cursor=stream.get_cursor("my-consumer"))
        assert events == []
        assert last_id is None
        if last_id:
            stream.set_cursor("my-consumer", last_id)
        assert stream.get_cursor("my-consumer") == e1.id

        # Third poll must not replay the already-delivered event.
        events, last_id = stream.read(cursor=stream.get_cursor("my-consumer"))
        assert events == []
        assert last_id is None
