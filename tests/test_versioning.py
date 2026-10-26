"""EventVersioner contract: chained migration, passthrough (Task 2)."""

import pytest

from purr.event import Event, EventType
from purr.versioning import EventVersioner, MigrationGapError


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


def test_migrate_does_not_mutate_input():
    """migrate() is a pure transform: the stored event keeps its old schema."""
    v = EventVersioner()
    v.register_migration("users", 1, 2, lambda p: {**p, "v2": True})
    original = _ev({"a": 1}, version=1)
    payload_before = dict(original.payload)
    version_before = original.version

    migrated = v.migrate(original)

    assert migrated is not original
    assert migrated.version == 2
    assert migrated.payload == {"a": 1, "v2": True}
    assert original.version == version_before == 1
    assert original.payload == payload_before == {"a": 1}


def test_versioner_raises_on_chain_gap():
    """A missing step in the chain must fail loudly, not ship the old schema."""
    v = EventVersioner()
    v.register_migration("users", 1, 2, lambda p: {**p, "v2": True})
    v.register_migration("users", 3, 4, lambda p: {**p, "v4": True})

    # v1 migrates to v2, then the 2 -> 3 step is missing.
    with pytest.raises(MigrationGapError, match="users v2 -> v3"):
        v.migrate(_ev({"a": 1}, version=1))

    # No migration at the event's own version either: the gap is at v1.
    gap_at_start = EventVersioner()
    gap_at_start.register_migration("users", 3, 4, lambda p: {**p, "v4": True})
    with pytest.raises(MigrationGapError, match="users v1 -> v2"):
        gap_at_start.migrate(_ev({"a": 1}, version=1))

    # Events already at (or past) the latest version pass through untouched.
    out = v.migrate(_ev({"a": 1}, version=4))
    assert out.version == 4
    assert out.payload == {"a": 1}
