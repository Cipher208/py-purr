"""EventVersioner contract: chained migration, passthrough (Task 2)."""
from purr.event import Event, EventType
from purr.versioning import EventVersioner


def _ev(payload, version=1):
    return Event(type=EventType.STORE, topic="users", payload=payload, version=version)


def test_migrates_v1_to_v3_chain():
    v = EventVersioner()
    v.register_migration("users", 1, 2, lambda p: {**p, "v2": True})
    v.register_migration("users", 2, 3, lambda p: {**p, "v3": True})
    out = v.migrate(_ev({"a": 1}))
    assert out.version == 3
    assert out.payload == {"a": 1, "v2": True, "v3": True}
    assert v.get_latest_version("users") == 3
    assert v.get_migrations("users") == [1, 2]


def test_unknown_topic_passes_through():
    v = EventVersioner()
    ev = _ev({"a": 1})
    assert v.migrate(ev) is ev
    assert v.get_latest_version("nope") == 1
