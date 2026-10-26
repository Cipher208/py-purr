"""P1-8 fix: per-engine migration registry — many engines, one db file."""

import sqlite3

from purr import Event, EventStream, EventType, StateMachine, Store


def test_two_engines_shared_db_file(tmp_path):
    """Audit scenario: Store(shared.db) then EventStream(shared.db).
    Pre-fix, EventStream saw the file-global user_version=1 and skipped its
    migrations -> 'no such table: events'."""
    db = tmp_path / "shared.db"
    store = Store(db)
    store.set("k", "v")
    stream = EventStream(db)
    stream.append(Event(type=EventType.SYSTEM, topic="t", payload={"x": 1}))
    events, _ = stream.read()
    assert len(events) == 1
    assert store.get("k") == "v"
    store.close()
    stream.close()


def test_state_machine_third_engine_shared_db(tmp_path):
    """Third engine on the same file also gets its own tables."""
    db = tmp_path / "shared.db"
    Store(db).close()
    EventStream(db).close()
    sm = StateMachine("m", db_path=db)
    sm.add_transition("idle", "done", "go")
    sm.set_state("idle")
    assert sm.send("go") is True
    sm.close()


def test_legacy_user_version_db_upgrade(tmp_path):
    """Legacy db: user_version=1, no _purr_schema. Must upgrade without
    data loss and register the engine."""
    db = tmp_path / "legacy.db"
    # Build a legacy v1 EventStream db by hand (old schema, no registry).
    conn = sqlite3.connect(str(db))
    conn.executescript(
        """
        CREATE TABLE events (
            id TEXT PRIMARY KEY, type TEXT NOT NULL, topic TEXT NOT NULL,
            payload TEXT NOT NULL DEFAULT '{}', correlation_id TEXT,
            timestamp TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1,
            source TEXT NOT NULL DEFAULT '', metadata TEXT NOT NULL DEFAULT '{}'
        );
        CREATE TABLE cursors (name TEXT PRIMARY KEY, last_event_id TEXT, updated_at TEXT NOT NULL);
        """
    )
    conn.execute(
        "INSERT INTO events (id, type, topic, payload, timestamp)"
        " VALUES ('e1', 'system', 't', '{}', '2026-01-01T00:00:00+00:00')"
    )
    conn.execute("PRAGMA user_version=1")
    conn.commit()
    conn.close()

    stream = EventStream(db)
    events, _ = stream.read()
    assert [e.id for e in events] == ["e1"]  # data preserved
    # v2 index present (upgrade applied)
    idx = stream._get_conn().execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_events_topic_ts'"
    ).fetchone()
    assert idx is not None
    # engine registered in the per-engine registry
    reg = stream._get_conn().execute(
        "SELECT version FROM _purr_schema WHERE engine='event_stream'"
    ).fetchone()
    assert reg is not None and reg[0] == 2
    stream.close()


def test_registered_engine_applies_new_migration_version(tmp_path):
    """An engine already registered at v1 picks up a newly added v2."""
    from purr.backend import SQLiteBackend

    class Evolving(SQLiteBackend):
        SCHEMA_VERSION = 2
        ENGINE_NAME = "evolving"
        MIGRATIONS: dict[int, str] = {}

        def _init_db(self):
            self.run_migrations()

    db = tmp_path / "evo.db"
    Evolving.MIGRATIONS = {1: "CREATE TABLE IF NOT EXISTS a (id INTEGER);"}
    Evolving(db).close()
    Evolving.MIGRATIONS = {
        1: "CREATE TABLE IF NOT EXISTS a (id INTEGER);",
        2: "CREATE TABLE IF NOT EXISTS b (id INTEGER);",
    }
    m2 = Evolving(db)
    tables = {
        r[0]
        for r in m2._get_conn().execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    assert "b" in tables
    row = m2._get_conn().execute(
        "SELECT version FROM _purr_schema WHERE engine='evolving'"
    ).fetchone()
    assert row[0] == 2
    m2.close()
