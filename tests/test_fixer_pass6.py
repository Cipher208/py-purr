"""Fixer tests, заход 6: retention validation, close() state reset,
publish_sync ordering, async error callback, registry clamp."""

from __future__ import annotations

import asyncio
import threading
import warnings

import pytest

from purr import Event, EventBus, EventType
from purr.backend import SQLiteBackend
from purr.event_stream import EventStream
from purr.store import Store

# ---------------- Cycle 1: retention parameter validation ----------------


@pytest.mark.parametrize("bad", [-1, 0, 2.9, "2", True])
def test_max_events_rejects_invalid(tmp_path, bad):
    """max_events=-1 became SQLite `LIMIT -1` (no limit at all), 0 wiped the
    whole stream: both silently changed or disabled retention."""
    with pytest.raises(ValueError, match="max_events must be a positive int or None"):
        EventStream(tmp_path / "ev.db", max_events=bad)


@pytest.mark.parametrize("bad", [-1, 0, "2", True])
def test_max_age_rejects_invalid(tmp_path, bad):
    with pytest.raises(ValueError, match="max_age_seconds must be a positive number or None"):
        EventStream(tmp_path / "ev.db", max_age_seconds=bad)


def test_retention_valid_values_pass(tmp_path):
    EventStream(tmp_path / "a.db", max_events=1).close()
    EventStream(tmp_path / "b.db", max_age_seconds=0.5).close()
    EventStream(tmp_path / "c.db", max_events=None, max_age_seconds=None).close()


# ---------------- Cycle 2: close() resets per-thread transaction state ----------------


def test_close_resets_thread_state(tmp_path):
    """A close() in the middle of a transaction must not poison the thread.

    The transaction flag and the journal buffer live in threading.local and
    outlive the connection, so after close() every later transaction() raised
    "nested transaction() is not supported" forever.
    """
    store = Store(tmp_path / "s.db", journal=EventStream(tmp_path / "ev.db"))
    ctx = store.transaction()
    ctx.__enter__()  # open a transaction and deliberately not leave it
    assert store._in_transaction is True
    store.set("buffered", "v")
    assert store._journal_buffer  # journal event parked for the open txn

    store.close()

    assert store._in_transaction is False
    assert store._journal_buffer == []
    with store.transaction():
        store.set("after", "v2")
    assert store.get("after") == "v2"


def test_close_leaves_other_threads_alone(tmp_path):
    """Only the closing thread's state is reset (per-thread by design)."""
    store = Store(tmp_path / "s.db")
    ctx = store.transaction()
    ctx.__enter__()
    assert store._in_transaction is True

    t = threading.Thread(target=store.close)
    t.start()
    t.join()

    # Another thread's close() must not clear THIS thread's transaction.
    assert store._in_transaction is True
    ctx.__exit__(None, None, None)
    assert store._in_transaction is False
    store.set("k", "v")
    assert store.get("k") == "v"


# ---------------- Cycle 3: publish_sync ordering / partial dispatch ----------------


def test_publish_sync_no_partial_dispatch_in_loop():
    """Inside a running loop publish_sync must fail BEFORE any handler runs.

    It used to invoke the sync handlers while collecting coroutines and only
    then discover the running loop: the side effects had already happened
    when RuntimeError flew.
    """
    bus = EventBus()
    log: list[str] = []

    bus.subscribe("t", lambda e: log.append("sync"))

    async def async_handler(event: Event) -> None:
        log.append("async")

    bus.subscribe("t", async_handler)

    async def inside() -> None:
        with pytest.raises(RuntimeError, match="await bus.publish"):
            bus.publish_sync(Event(type=EventType.SYSTEM, topic="t"))

    asyncio.run(inside())
    assert log == []


def test_publish_sync_preserves_subscription_order():
    """async-1, sync-2, sync-3 must be delivered as 1, 2, 3 (not 2, 3, 1)."""
    bus = EventBus()
    order: list[str] = []

    async def async_first(event: Event) -> None:
        order.append("1")

    bus.subscribe("t", async_first)
    bus.subscribe("t", lambda e: order.append("2"))
    bus.subscribe("t", lambda e: order.append("3"))

    bus.publish_sync(Event(type=EventType.SYSTEM, topic="t"))
    assert order == ["1", "2", "3"]


# ---------------- Cycle 4: async on_handler_error is awaited ----------------


def test_async_error_callback_awaited():
    """An async on_handler_error callback must actually run (no lost error,
    no "coroutine was never awaited" RuntimeWarning)."""
    calls: list[int] = []

    async def on_error(event: Event, exc: BaseException) -> None:
        calls.append(1)

    bus = EventBus(on_handler_error=on_error)

    async def broken(event: Event) -> None:
        raise ValueError("boom")

    bus.subscribe("t", broken)
    event = Event(type=EventType.SYSTEM, topic="t")

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        asyncio.run(bus.publish(event))

    assert calls == [1]
    assert [w for w in caught if issubclass(w.category, RuntimeWarning)] == []


def test_sync_error_callback_still_reported():
    """The sync callback path is unchanged: called once per failing handler."""
    reported: list[BaseException] = []
    bus = EventBus(on_handler_error=lambda event, exc: reported.append(exc))

    def broken(event: Event) -> None:
        raise ValueError("boom")

    bus.subscribe("t", broken)
    bus.publish_sync(Event(type=EventType.SYSTEM, topic="t"))
    assert len(reported) == 1
    assert isinstance(reported[0], ValueError)


# ---------------- Cycle 5: registry version must match the clamp ----------------


class _ClampedEngine(SQLiteBackend):
    """SCHEMA_VERSION ahead of MIGRATIONS: the registry row used to record 1
    while user_version was clamped to 3, and stayed 1 on every later open."""

    ENGINE_NAME = "clamped"
    SCHEMA_VERSION = 3
    MIGRATIONS = {1: "CREATE TABLE IF NOT EXISTS clamped_a (id INTEGER);"}

    def _init_db(self) -> None:
        self.run_migrations()


def test_registry_records_clamped_version(tmp_path):
    """The registry row must be the final value, agreeing with user_version.

    SCHEMA_VERSION=3 with MIGRATIONS={1} used to write 1 to the registry and
    clamp user_version to 3 — two different answers to "which schema is
    installed?", and the registry never moved. Documented resolution: the
    registry records the highest applied migration (1), never more than
    SCHEMA_VERSION, and user_version is raised to that same value. Recording
    3 would make a v2/v3 migration added later look already applied.
    """
    db = tmp_path / "c.db"
    engine = _ClampedEngine(db)
    conn = engine._get_conn()
    registry = conn.execute(
        "SELECT version FROM _purr_schema WHERE engine='clamped'"
    ).fetchone()[0]
    user_version = conn.execute("PRAGMA user_version").fetchone()[0]
    assert registry == 1
    assert registry == user_version
    assert registry <= _ClampedEngine.SCHEMA_VERSION
    engine.close()

    # Reopening neither rewrites nor downgrades the row.
    again = _ClampedEngine(db)
    assert again.run_migrations() == 0
    row = again._get_conn().execute(
        "SELECT version FROM _purr_schema WHERE engine='clamped'"
    ).fetchone()[0]
    assert row == 1
    assert again._get_conn().execute("PRAGMA user_version").fetchone()[0] == 1
    again.close()


