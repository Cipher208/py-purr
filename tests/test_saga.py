"""Tests for PURR Saga."""

import asyncio
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

import purr
from purr import EventStream, Saga, SagaStatus, StateMachine


@pytest.mark.asyncio
async def test_saga_success():
    async def step1(data):
        return {"step1": True}

    async def step2(data):
        return {"step2": True}

    saga = Saga("test")
    saga.add_step("step1", step1)
    saga.add_step("step2", step2)

    result = await saga.execute({"start": True})
    assert result == {"start": True, "step1": True, "step2": True}
    assert saga.status == SagaStatus.COMPLETED


@pytest.mark.asyncio
async def test_saga_compensation():
    call_log = []

    async def step1(data):
        call_log.append("step1")
        return {"step1": True}

    async def step2(data):
        call_log.append("step2")
        raise ValueError("step2 failed")

    async def compensate1(data):
        call_log.append("compensate1")

    saga = Saga("test")
    saga.add_step("step1", step1, compensation=compensate1)
    saga.add_step("step2", step2)

    with pytest.raises(ValueError):
        await saga.execute()

    assert call_log == ["step1", "step2", "compensate1"]
    assert saga.status == SagaStatus.COMPENSATED


@pytest.mark.asyncio
async def test_saga_step_failure():
    async def step1(data):
        return {"step1": True}

    async def step2(data):
        raise RuntimeError("boom")

    saga = Saga("test")
    saga.add_step("step1", step1)
    saga.add_step("step2", step2)

    with pytest.raises(RuntimeError):
        await saga.execute()

    # Status is compensated (even without explicit compensation functions)
    assert saga.status in (SagaStatus.FAILED, SagaStatus.COMPENSATED)


def test_saga_get_state():
    saga = Saga("test")
    state = saga.get_state()
    assert state["name"] == "test"
    assert state["status"] == "pending"
    assert state["current_step"] == 0


class TestSagaPersistence:
    """A crashed saga must be VISIBLE in the same SQLite file, not resumed.

    Contract: table only (no new journal op), db_path optional, no resume().
    Every database read below uses its own sqlite3.connect, never the Saga
    object; every connection and every engine is closed before teardown.
    """

    ROOT = Path(__file__).resolve().parents[1]

    CHILD = """\
import asyncio
import os
import sys
from pathlib import Path
from purr import Saga

DB, MODE, MARK = sys.argv[1], sys.argv[2], Path(sys.argv[3])


def build():
    try:
        return Saga("crash_demo", db_path=DB)
    except TypeError as exc:
        if "db_path" not in str(exc):
            raise
        return Saga("crash_demo")


async def reserve(data):
    return {"reserved": True}


async def charge(data):
    return {"charged": True}


async def send_mail(data):
    MARK.write_text("mail sent", encoding="utf-8")
    os._exit(0)


async def go():
    saga = build()
    saga.add_step("reserve", reserve)
    if MODE == "complete":
        saga.add_step("charge", charge)
    else:
        saga.add_step("send_mail", send_mail)
    await saga.execute({"order": 7})


asyncio.run(go())
os._exit(0)
"""

    @staticmethod
    def _saga(name, db_path):
        """Bind the saga to db_path if the constructor accepts it.

        On the base commit the kwarg does not exist: the saga still executes
        in memory, so a missing checkpoint is the observed defect itself and
        never a TypeError/AttributeError standing in for it.
        """
        try:
            return Saga(name, db_path=str(db_path))
        except TypeError as exc:
            if "db_path" not in str(exc):
                raise
            return Saga(name)

    @staticmethod
    def _close(saga):
        """Release a saga-owned connection, if the implementation keeps one."""
        closer = getattr(saga, "close", None)
        if closer is not None:
            closer()

    @staticmethod
    async def _ok(data):
        return {"ok": True}

    @staticmethod
    async def _boom(data):
        raise RuntimeError("boom")

    @staticmethod
    def _tables(db_path):
        conn = sqlite3.connect(str(db_path))
        try:
            return [
                row[0]
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            ]
        finally:
            conn.close()

    @staticmethod
    def _registry(db_path):
        conn = sqlite3.connect(str(db_path))
        try:
            return [row[0] for row in conn.execute("SELECT engine FROM _purr_schema")]
        finally:
            conn.close()

    @staticmethod
    def _snapshots(db_path):
        """Read the checkpoint with a SEPARATE connection, never via Saga."""
        conn = sqlite3.connect(str(db_path))
        try:
            conn.row_factory = sqlite3.Row
            tables = [
                row[0]
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            ]
            assert "saga_state" in tables, (
                f"expected saga_state in the shared database, tables={tables}"
            )
            cur = conn.execute("SELECT * FROM saga_state")
            cols = [d[0] for d in cur.description]
            rows = cur.fetchall()
        finally:
            conn.close()
        states = []
        for row in rows:
            state = {col: row[col] for col in cols}
            for col in cols:
                value = row[col]
                if isinstance(value, str) and value.lstrip().startswith(("{", "[")):
                    try:
                        parsed = json.loads(value)
                    except (TypeError, ValueError):
                        continue
                    if isinstance(parsed, dict):
                        state.update(parsed)
                    elif isinstance(parsed, list):
                        state.setdefault("steps", parsed)
            states.append(state)
        return states

    @staticmethod
    def _journal(db_path):
        conn = sqlite3.connect(str(db_path))
        try:
            return [
                (row[0], row[1], json.loads(row[2]).get("op"))
                for row in conn.execute("SELECT type, topic, payload FROM events")
            ]
        finally:
            conn.close()

    @classmethod
    def _run_child(cls, tmp_path, db_path, mode):
        script = tmp_path / "child_saga.py"
        script.write_bytes(cls.CHILD.encode("utf-8"))
        env = {**os.environ, "PYTHONPATH": str(cls.ROOT)}
        return subprocess.run(  # noqa: S603 - fixed interpreter + fixed local script
            [
                sys.executable,
                str(script),
                str(db_path),
                mode,
                str(tmp_path / "mail.txt"),
            ],
            cwd=str(cls.ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )

    def test_checkpoint_schema_lives_in_the_shared_database(self, tmp_path):
        db = tmp_path / "shared.db"
        es = EventStream(str(db))
        saga = self._saga("order", db)
        try:
            saga.add_step("reserve", self._ok)
            asyncio.run(saga.execute({"order": 7}))
        finally:
            self._close(saga)
            es.close()
        tables, registry = self._tables(db), self._registry(db)
        assert ("saga_state" in tables, "saga" in registry) == (True, True), (
            f"tables={tables} registry={registry}"
        )

    def test_another_process_reads_name_status_and_step_after_crash(self, tmp_path):
        db = tmp_path / "crash.db"
        proc = self._run_child(tmp_path, db, "complete")
        assert proc.returncode == 0, f"child stdout={proc.stdout!r} stderr={proc.stderr!r}"
        states = self._snapshots(db)
        snap = states[0] if states else {}
        assert (snap.get("name"), snap.get("status"), snap.get("current_step")) == (
            "crash_demo",
            "completed",
            1,
        ), f"snapshot={snap} states={states}"

    def test_crash_mid_step_leaves_a_non_completed_checkpoint(self, tmp_path):
        db = tmp_path / "midcrash.db"
        proc = self._run_child(tmp_path, db, "midstep")
        assert proc.returncode == 0, f"child stdout={proc.stdout!r} stderr={proc.stderr!r}"
        states = self._snapshots(db)
        snap = states[0] if states else {}
        assert snap.get("status") not in (None, "completed"), (
            f"snapshot after a mid-step crash={snap}; a checkpoint written only "
            "at completion leaves no row"
        )

    def test_failed_step_checkpoint_is_not_completed(self, tmp_path):
        db = tmp_path / "failed.db"
        saga = self._saga("order", db)
        try:
            saga.add_step("reserve", self._ok)
            saga.add_step("charge", self._boom)
            with pytest.raises(RuntimeError, match="boom"):
                asyncio.run(saga.execute({"order": 7}))
        finally:
            self._close(saga)
        states = self._snapshots(db)
        snap = states[0] if states else {}
        assert snap.get("status") not in (None, "completed"), f"snapshot={snap}"

    def test_external_side_effect_survives_and_data_rolls_back(self, tmp_path):
        db = tmp_path / "side.db"
        mail = tmp_path / "letter.txt"
        saga = self._saga("order", db)

        async def reserve(data):
            return {"reserved": True}

        async def send_mail(data):
            mail.write_bytes(b"letter")
            raise RuntimeError("mail already sent")

        saga.add_step("reserve", reserve)
        saga.add_step("send_mail", send_mail)
        try:
            with pytest.raises(RuntimeError, match="mail already sent"):
                asyncio.run(saga.execute({"order": 7}))
        finally:
            self._close(saga)
        assert (mail.exists(), dict(saga.data), saga.status.value) == (
            True,
            {"order": 7},
            "compensated",
        )

    def test_checkpoint_omits_action_compensation_written_restore(self, tmp_path):
        db = tmp_path / "omit.db"
        saga = self._saga("order", db)
        try:
            saga.add_step("reserve", self._ok)
            asyncio.run(saga.execute({"order": 7}))
        finally:
            self._close(saga)
        states = self._snapshots(db)
        snap = states[0] if states else {}

        def keys_of(value):
            found = set()
            if isinstance(value, dict):
                found.update(value)
                for item in value.values():
                    found |= keys_of(item)
            elif isinstance(value, list):
                for item in value:
                    found |= keys_of(item)
            return found

        assert keys_of(snap) & {"written", "restore", "action", "compensation"} == set(), (
            f"snapshot keys={sorted(keys_of(snap))}"
        )

    def test_re_registration_does_not_replay_completed_steps(self, tmp_path):
        db = tmp_path / "resume.db"
        marker = tmp_path / "actions.log"

        async def step(data):
            with marker.open("a", encoding="utf-8") as handle:
                handle.write("ran\n")
            return {"done": True}

        first = self._saga("order", db)
        second = self._saga("order", db)
        try:
            first.add_step("reserve", step)
            asyncio.run(first.execute())
            second.add_step("reserve", step)
        finally:
            self._close(first)
            self._close(second)
        assert (marker.read_text(encoding="utf-8"), hasattr(Saga, "resume")) == (
            "ran\n",
            False,
        ), f"marker={marker.read_text(encoding='utf-8')!r} state={second.get_state()!r}"

    def test_get_state_shape_is_unchanged(self, tmp_path):
        saga = self._saga("shape", tmp_path / "shape.db")
        try:
            state = saga.get_state()
        finally:
            self._close(saga)
        assert (set(state), state["status"], state["current_step"]) == (
            {"name", "status", "current_step", "data", "steps"},
            "pending",
            0,
        ), f"state={state}"

    def test_db_path_is_optional_for_legacy_callers(self):
        try:
            saga = Saga("legacy_tour")
        except TypeError as exc:
            raise AssertionError(
                f"Saga(name) broke the legacy contract: db_path must stay optional, got {exc!r}"
            ) from exc
        saga.add_step("reserve", self._ok)
        assert asyncio.run(saga.execute({"order": 7})) == {"order": 7, "ok": True}

    def test_journal_has_no_new_saga_op(self, tmp_path):
        db = tmp_path / "journal.db"
        es = EventStream(str(db))
        saga = self._saga("order", db)
        try:
            saga.add_step("reserve", self._ok)
            asyncio.run(saga.execute({"order": 7}))
        finally:
            self._close(saga)
            es.close()
        assert self._journal(db) == [], f"journal entries={self._journal(db)}"

    def test_public_exports_and_callback_error_are_intact(self):
        assert (len(purr.__all__), "CallbackError" in purr.__all__) == (25, True), (
            f"__all__={purr.__all__}"
        )

    def test_unserializable_data_does_not_break_the_checkpoint(self, tmp_path):
        db = tmp_path / "ambiguous.db"

        class Ambiguous:
            def __eq__(self, other):
                return self

            def __ne__(self, other):
                return self

            def __bool__(self):
                raise ValueError("ambiguous truth value")

            __hash__ = None

        saga = self._saga("order", db)
        try:
            saga.add_step("reserve", self._ok)
            result = asyncio.run(saga.execute({"order": 7, "arr": Ambiguous()}))
        finally:
            self._close(saga)
        states = self._snapshots(db)
        snap = states[0] if states else {}
        assert (len(states), snap.get("status"), result["order"]) == (1, "completed", 7), (
            f"states={states}"
        )

    def test_adr001_state_and_journal_event_share_one_file(self, tmp_path):
        db = tmp_path / "adr001.db"
        es = EventStream(str(db))
        sm = StateMachine("pipeline", db_path=str(db), journal=es)
        try:
            sm.add_transition("idle", "processing", "go")
            sm.set_state("idle")
            sm.send("go")
            saga = self._saga("order", db)
            try:
                saga.add_step("reserve", self._ok)
                asyncio.run(saga.execute({"order": 7}))
            finally:
                self._close(saga)
        finally:
            sm.close()
            es.close()
        conn = sqlite3.connect(str(db))
        try:
            machines = conn.execute("SELECT count(*) FROM state_machines").fetchone()[0]
            ops = [
                json.loads(row[0]).get("op") for row in conn.execute("SELECT payload FROM events")
            ]
        finally:
            conn.close()
        assert (machines, ops) == (1, ["set", "transition"]), f"machines={machines} ops={ops}"
