"""Fixer tests, заход 3: lock/transaction leaks left by the pass-2 changes."""

import sqlite3
import time
from datetime import UTC, datetime

import pytest

from purr import Event, EventType, Store
from purr.event_stream import EventStream


def _event(event_id: str | None = None, topic: str = "t1", payload: dict | None = None) -> Event:
    kwargs: dict = {"type": EventType.SYSTEM, "topic": topic}
    if payload is not None:
        kwargs["payload"] = payload
    ev = Event(**kwargs)
    if event_id is not None:
        ev.id = event_id
    return ev


# ---------------- Cycle 1: prune with nothing to delete must not hold a write txn ----


def test_prune_without_victims_releases_lock(tmp_path):
    """maintain() with retention configured but nothing to prune must not lock the file.

    pysqlite opens an implicit transaction on the first DELETE; committing only
    when rowcount != 0 leaves that transaction (and its RESERVED lock) open, so
    every other writer — a second instance, another process — blocks on
    "database is locked" until close().
    """
    db = tmp_path / "ev.db"
    stream = EventStream(db, max_events=10)
    for i in range(3):
        stream.append(_event(event_id=f"e{i}"))

    report = stream.maintain()
    assert report["pruned_events"] == 0
    assert stream._get_conn().in_transaction is False

    # the file is immediately writable from a fresh connection
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


# ---------------- Cycle 2: opening an up-to-date db must not write -------------------


class _QueryOnlyStore(Store):
    """Store whose connections refuse writes (stands in for a read-only file)."""

    def _get_conn(self):
        conn = super()._get_conn()
        conn.execute("PRAGMA query_only=ON")
        return conn


def test_migrations_do_not_write_when_already_current(tmp_path):
    """Re-opening a migrated db must not issue CREATE/INSERT/clamp writes.

    Pre-fix run_migrations() wrote on every open, so an already-migrated but
    read-only database failed with "attempt to write a readonly database".
    """
    db = tmp_path / "store.db"
    first = Store(db)
    first.set("k", "v")
    first.close()

    again = _QueryOnlyStore(db)  # must not raise: nothing left to write
    assert again.get("k") == "v"
    row = (
        again._get_conn()
        .execute("SELECT version FROM _purr_schema WHERE engine='store'")
        .fetchone()
    )
    assert row is not None and row[0] == Store.SCHEMA_VERSION
    again.close()


def test_open_while_other_instance_in_transaction(tmp_path):
    """A second instance opens at once while the first holds BEGIN IMMEDIATE.

    Pre-fix the open needed a write lock (registry CREATE+INSERT), so it slept
    on the 5 s busy timeout and failed with "database is locked" instead.
    """
    db = tmp_path / "store.db"
    first = Store(db)
    first.set("k", "v")
    first._get_conn().execute("BEGIN IMMEDIATE")

    started = time.perf_counter()
    try:
        second = Store(db)
        elapsed = time.perf_counter() - started
        assert elapsed < 2.0, f"open waited {elapsed:.2f}s for the busy timeout"
        assert second.get("k") == "v"
        second.close()
    finally:
        first._get_conn().rollback()
        first.close()


# ---------------- Cycle 3: append_many must be atomic on *any* error ----------------


def test_append_many_atomic_on_any_error(tmp_path):
    """A non-IntegrityError mid-batch must roll back the partial batch too.

    append_many() only rolled back on IntegrityError, so a TypeError from an
    unserializable payload left the events inserted before it in an open
    transaction — which the next unrelated append() committed, resurrecting the
    rejected batch. The docstring promises a full rollback.
    """
    stream = EventStream(tmp_path / "ev.db")
    stream.append(_event(event_id="keep"))

    batch = [
        _event(event_id="ok-1"),
        _event(event_id="bad", payload={"o": object()}),
        _event(event_id="ok-2"),
    ]
    with pytest.raises(TypeError):
        stream.append_many(batch)

    assert stream.count() == 1  # only the pre-existing event survived
    assert stream._get_conn().in_transaction is False

    # the next unrelated append must not commit the rejected batch
    stream.append(_event(event_id="after"))
    ids = sorted(e.id for e in stream.read()[0])
    assert ids == ["after", "keep"]
    stream.close()


# ---------------- Cycle 4: incr() must not BEGIN on top of a leftover txn -----------


def test_incr_survives_leftover_implicit_transaction(tmp_path):
    """incr() must reuse a leftover implicit transaction, not BEGIN on top of it.

    A raw write through the shared connection (the same state a failed
    statement used to leave behind) opens an implicit transaction. incr()
    then issued BEGIN IMMEDIATE unconditionally (own_txn tracks only
    transaction()) and died with "cannot start a transaction within a
    transaction" before touching the data.
    """
    store = Store(tmp_path / "store.db")
    try:
        conn = store._get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO kv (key, value, type, created_at, updated_at)"
            " VALUES ('leftover', '1', 'int', 'now', 'now')"
        )
        assert conn.in_transaction is True

        assert store.incr("c") == 1
        assert store.get("c") == 1
        assert store._get_conn().in_transaction is False
    finally:
        store.close()
