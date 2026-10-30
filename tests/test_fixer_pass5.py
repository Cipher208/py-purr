"""Fixer tests, заход 5: the journal must not contradict what the commit did.

Two ways the store and the journal used to drift apart: incr() emitted its
event inside its own write transaction (subscribers saw data that was not
committed yet, and on a shared file the emit blocked on the store's own
RESERVED lock), and transaction() raised a flush error that looked like a
rollback although the data was already committed. The co-located journal
settles both: the event is written in the data's transaction, so there is
nothing left to flush and no "committed, but not journaled" state.
"""

import sqlite3
import time

import pytest

from purr import EventStream, Store


def test_incr_journals_inside_the_transaction(tmp_path):
    """incr()'s event joins the increment's own write transaction.

    A second connection sees nothing at emit time: the counter and its event
    appear together. The old ordering emitted after the commit, so the spy saw
    the counter already durable while the event was still pending — the gap.
    """
    es = EventStream(tmp_path / "s.db")
    s = Store(tmp_path / "s.db", journal=es)
    visible: list[bool] = []
    original_emit = s._journal_emit

    def spy_emit(payload):
        conn = sqlite3.connect(tmp_path / "s.db")
        try:
            row = conn.execute("SELECT value FROM kv WHERE key = ?", (payload["key"],)).fetchone()
        finally:
            conn.close()
        visible.append(row is not None)
        original_emit(payload)

    s._journal_emit = spy_emit
    try:
        assert s.incr("c") == 1
        assert visible == [False]
    finally:
        s.close()
        es.close()


def test_shared_file_incr_with_journal_works(tmp_path):
    """incr() must not deadlock against its own journal on a shared file."""
    db = tmp_path / "shared.db"
    es = EventStream(db)
    s = Store(db, journal=es)
    try:
        s.set("a", 1)
        started = time.monotonic()
        assert s.incr("a") == 2
        elapsed = time.monotonic() - started
        assert s.get("a") == 2
        # pre-fix: blocked for the 5 s busy timeout, then "database is locked"
        assert elapsed < 2.0
    finally:
        s.close()
        es.close()


class _FailingStream(EventStream):
    """A real journal stream that rejects chosen keys.

    Both hooks are overridden on purpose: the old ordering appended after the
    commit, the new one inserts inside the data's transaction, and the same
    injected failure has to reach the code under test in either shape.
    """

    def __init__(self, db_path, bad_keys: set[str]) -> None:
        self.bad_keys = bad_keys
        super().__init__(db_path)

    def _reject(self, event) -> None:
        if event.payload.get("key") in self.bad_keys:
            raise sqlite3.OperationalError("disk I/O error")

    def append(self, event) -> None:
        self._reject(event)
        super().append(event)

    def insert_in(self, conn, event) -> None:
        self._reject(event)
        super().insert_in(conn, event)


def test_journal_failure_rolls_back_the_data(tmp_path):
    """A failing event insert rolls the data back; no gap is left to report.

    This is the class-of-failure change of the co-located journal: "the data
    is durable, the journal is not" is no longer reachable, so nothing can be
    raised after a commit — the commit itself does not happen.
    """
    db = tmp_path / "s.db"
    journal = _FailingStream(db, {"b", "c"})
    s = Store(db, journal=journal)
    try:
        with pytest.raises(sqlite3.OperationalError), s.transaction():
            s.set("a", 1)
            s.set("b", 2)
            s.set("c", 3)

        # nothing survived: the keys went back together with their events
        conn = sqlite3.connect(str(db))
        try:
            rows = dict(conn.execute("SELECT key, value FROM kv").fetchall())
        finally:
            conn.close()
        assert rows == {}
    finally:
        s.close()
        journal.close()
