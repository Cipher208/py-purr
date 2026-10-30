"""Tests for PURR State Machine."""

import sqlite3

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
