"""Tests for PURR State Machine."""

import json
import sqlite3
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from purr import EventStream, StateMachine


@pytest.fixture
def sm(tmp_path):
    """Create a temporary state machine."""
    return StateMachine("test", db_path=tmp_path / "state.db")


class TestStateMachine:
    def test_initial_state(self, sm):
        assert sm.current_state is None

    def test_set_state(self, sm):
        sm.set_state("idle")
        assert sm.current_state == "idle"

    def test_transition(self, sm):
        sm.add_transition("idle", "active", "start")
        sm.set_state("idle")
        assert sm.send("start") is True
        assert sm.current_state == "active"

    def test_transition_not_found(self, sm):
        sm.add_transition("idle", "active", "start")
        sm.set_state("idle")
        assert sm.send("unknown") is False
        assert sm.current_state == "idle"

    def test_guard(self, sm):
        sm.add_transition("idle", "active", "start", guard=lambda s, d: d.get("allowed", False))
        sm.set_state("idle")
        assert sm.send("start", {"allowed": False}) is False
        assert sm.current_state == "idle"
        assert sm.send("start", {"allowed": True}) is True
        assert sm.current_state == "active"

    def test_action(self, sm):
        sm.add_transition(
            "idle",
            "active",
            "start",
            action=lambda s, d: {"count": d.get("count", 0) + 1},
        )
        sm.set_state("idle")
        sm.send("start", {"count": 5})
        assert sm.state_data["count"] == 6

    def test_on_enter(self, sm):
        entered = []
        sm.on_enter("active", lambda s: entered.append(s.name))
        sm.add_transition("idle", "active", "start")
        sm.set_state("idle")
        sm.send("start")
        assert entered == ["active"]

    def test_on_exit(self, sm):
        exited = []
        sm.on_exit("idle", lambda s: exited.append(s.name))
        sm.add_transition("idle", "active", "start")
        sm.set_state("idle")
        sm.send("start")
        assert exited == ["idle"]


class TestStateMachinePersistence:
    def test_persistence(self, tmp_path):
        db = tmp_path / "state.db"
        sm1 = StateMachine("test", db_path=db)
        sm1.set_state("idle")
        sm1.add_transition("idle", "active", "start")
        sm1.send("start")

        sm2 = StateMachine("test", db_path=db)
        assert sm2.current_state == "active"

    def test_snapshot(self, sm):
        sm.set_state("idle")
        sm.add_transition("idle", "active", "start")
        sm.send("start")
        sm.snapshot()

        snapshots = sm.get_snapshots()
        assert len(snapshots) == 1
        assert snapshots[0]["state"] == "active"

    def test_restore_snapshot(self, sm):
        sm.set_state("idle")
        sm.add_transition("idle", "active", "start")
        sm.send("start")
        sm.snapshot()

        sm.send("complete")  # No transition defined
        sm.set_state("error")

        sm.restore_snapshot()
        assert sm.current_state == "active"

    def test_prune_snapshots_keeps_newest(self, sm):
        sm.set_state("idle")
        for _ in range(5):
            sm.snapshot()
        assert len(sm.get_snapshots()) == 5
        assert sm.prune_snapshots(keep=2) == 3
        assert len(sm.get_snapshots()) == 2


class TestStateMachineJournal:
    def test_transition_appended_to_journal(self, tmp_path):
        """The transition event is written in the state's own transaction.

        The spy opens a second connection: at emit time it must still see no
        row, because the state has not been committed yet. Emitting after the
        commit is what let a transition be lost while its state survived.
        """
        db = tmp_path / "s.db"
        es = EventStream(db)
        sm = StateMachine("m", db_path=db, journal=es)
        seen: list[bool] = []
        original_emit = sm._journal_emit

        def spy_emit(payload):
            conn = sqlite3.connect(str(db))
            try:
                row = conn.execute(
                    "SELECT current_state FROM state_machines WHERE name = 'm'"
                ).fetchone()
            finally:
                conn.close()
            # "already visible" means this very transition, not the row left
            # behind by the previous set_state()
            seen.append(row is not None and row[0] == payload["to"])
            original_emit(payload)

        sm._journal_emit = spy_emit
        sm.add_transition("idle", "flow", "start")
        sm.set_state("idle")
        assert sm.send("start") is True
        events, _ = es.read(topic="fsm")
        assert [(e.payload["op"], e.payload.get("from"), e.payload.get("to")) for e in events] == [
            ("set", None, "idle"),
            ("transition", "idle", "flow"),
        ]
        assert seen == [False, False]
        sm.close()
        es.close()

    def test_foreign_journal_path_rejected(self, tmp_path):
        """Same journal contract as Store: a journal on another file is refused."""
        es = EventStream(tmp_path / "j.db")
        with pytest.raises(ValueError, match="same file as the data"):
            StateMachine("m", db_path=tmp_path / "s.db", journal=es)
        es.close()

    def test_no_journal_no_stream_writes(self, tmp_path):
        es = EventStream(tmp_path / "j.db")
        sm = StateMachine("m", db_path=tmp_path / "s.db")
        sm.set_state("idle")
        events, _ = es.read(topic="fsm")
        assert events == []
        sm.close()
        es.close()


def _read_state(db: Path) -> tuple[str, dict[str, Any]]:
    """Read the persisted state through a connection of its own."""
    with closing(sqlite3.connect(str(db))) as conn:
        row = conn.execute(
            "SELECT current_state, state_data FROM state_machines WHERE name = 'm'"
        ).fetchone()
    return row[0], json.loads(row[1])


def _read_events(db: Path) -> list[tuple[str, str | None, str]]:
    """Read journal payloads through a connection of its own."""
    with closing(sqlite3.connect(str(db))) as conn:
        rows = conn.execute("SELECT payload FROM events ORDER BY timestamp, rowid").fetchall()
    parsed = [json.loads(row[0]) for row in rows]
    return [(event["op"], event.get("from"), event["to"]) for event in parsed]


@dataclass
class Rig:
    sm: StateMachine
    es: EventStream
    db: Path
    calls: list[tuple[str, str]]
    original_emit: Callable[[dict[str, Any]], None]

    def break_journal(self) -> None:
        def fail(payload: dict[str, Any]) -> None:
            raise RuntimeError("forced journal failure")

        self.sm._journal_emit = fail

    def restore_journal(self) -> None:
        self.sm._journal_emit = self.original_emit


@pytest.fixture
def rig(tmp_path):
    db = tmp_path / "state.db"
    es = EventStream(db)
    sm = StateMachine("m", db_path=db, journal=es)
    calls: list[tuple[str, str]] = []
    sm.on_exit("A", lambda state: calls.append(("exit", state.name)))
    sm.on_enter("B", lambda state: calls.append(("enter", state.name)))
    sm.add_transition("A", "B", "go")
    sm.set_state("A", {"marker": "old"})
    stand = Rig(sm=sm, es=es, db=db, calls=calls, original_emit=sm._journal_emit)
    yield stand
    # Teardown runs even when an assertion failed: an open SQLite handle on
    # Windows blocks pytest from removing tmp_path (PermissionError).
    stand.restore_journal()
    sm.close()
    es.close()


class TestStateMachineRollback:
    """A failed write must leave the machine and the database in agreement."""

    def test_send_keeps_memory_equal_to_database_after_failed_write(self, rig):
        rig.break_journal()
        with pytest.raises(RuntimeError):
            rig.sm.send("go", {"marker": "new"})
        assert (rig.sm.current_state, rig.sm.state_data) == _read_state(rig.db)

    def test_set_state_keeps_memory_equal_to_database_after_failed_write(self, rig):
        rig.break_journal()
        with pytest.raises(RuntimeError):
            rig.sm.set_state("Z", {"marker": "new"})
        assert (rig.sm.current_state, rig.sm.state_data) == _read_state(rig.db)

    def test_send_propagates_the_write_error(self, rig):
        rig.break_journal()
        with pytest.raises(RuntimeError) as excinfo:
            rig.sm.send("go", {"marker": "new"})
        assert str(excinfo.value) == "forced journal failure"

    def test_set_state_propagates_the_write_error(self, rig):
        rig.break_journal()
        with pytest.raises(RuntimeError) as excinfo:
            rig.sm.set_state("Z", {"marker": "new"})
        assert str(excinfo.value) == "forced journal failure"

    def test_failed_transition_calls_no_callbacks(self, rig):
        rig.break_journal()
        with pytest.raises(RuntimeError):
            rig.sm.send("go", {"marker": "new"})
        assert rig.calls == []

    def test_failed_transition_appends_no_event(self, rig):
        rig.break_journal()
        with pytest.raises(RuntimeError):
            rig.sm.send("go", {"marker": "new"})
        assert _read_events(rig.db) == [("set", None, "A")]

    def test_failed_transition_leaves_previous_state_in_database(self, rig):
        rig.break_journal()
        with pytest.raises(RuntimeError):
            rig.sm.send("go", {"marker": "new"})
        assert _read_state(rig.db) == ("A", {"marker": "old"})

    def test_successful_transition_changes_state_and_data(self, rig):
        rig.sm.send("go", {"marker": "new"})
        assert (rig.sm.current_state, rig.sm.state_data) == ("B", {"marker": "new"})

    def test_successful_transition_persists_state(self, rig):
        rig.sm.send("go", {"marker": "new"})
        assert _read_state(rig.db) == ("B", {"marker": "new"})

    def test_successful_transition_calls_callbacks_in_order(self, rig):
        rig.sm.send("go", {"marker": "new"})
        assert rig.calls == [("exit", "A"), ("enter", "B")]

    def test_successful_transition_appends_event(self, rig):
        rig.sm.send("go", {"marker": "new"})
        assert _read_events(rig.db) == [("set", None, "A"), ("transition", "A", "B")]

    def test_retry_after_failed_send_succeeds(self, rig):
        rig.break_journal()
        with pytest.raises(RuntimeError):
            rig.sm.send("go", {"marker": "new"})
        rig.restore_journal()
        assert (rig.sm.send("go", {"marker": "new"}), rig.sm.current_state) == (True, "B")
