"""Tests for PURR State Machine."""

import pytest
from purr import StateMachine


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
        sm.add_transition(
            "idle", "active", "start", guard=lambda s, d: d.get("allowed", False)
        )
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
