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

    def test_count_and_clear(self, stream):
        e1 = Event(type=EventType.SYSTEM, topic="t1", payload={})
        e2 = Event(type=EventType.SYSTEM, topic="t2", payload={})
        stream.append(e1)
        stream.append(e2)

        assert stream.count() == 2
        assert stream.count(topic="t1") == 1

        stream.clear()
        assert stream.count() == 0
