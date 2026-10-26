"""Fixer tests, заход 5: the journal must not contradict what the commit did.

Two ways the store and the journal drift apart: incr() emits its event inside
its own write transaction (subscribers see data that is not committed yet, and
on a shared file the emit blocks on the store's own RESERVED lock), and
transaction() raises a flush error that looks like a rollback although the
data is already committed.
"""

import sqlite3
import time

import pytest

from purr import EventStream, Store


def test_incr_journals_after_commit(tmp_path):
    """At journal-emit time, incr()'s data must already be visible to others."""
    es = EventStream(tmp_path / "j.db")
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
        assert visible == [True]
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


class _FlakyJournal:
    """Journal that rejects chosen keys, recording the rest."""

    def __init__(self, bad_keys: set[str]) -> None:
        self.bad_keys = bad_keys
        self.events: list = []

    def append(self, event) -> None:
        if event.payload.get("key") in self.bad_keys:
            raise sqlite3.OperationalError("disk I/O error")
        self.events.append(event)


def test_transaction_flush_failure_reports_committed(tmp_path):
    """A failed journal flush must not masquerade as a rolled-back commit."""
    from purr import JournalFlushError

    db = tmp_path / "s.db"
    journal = _FlakyJournal({"b", "c"})
    s = Store(db, journal=journal)
    try:
        with pytest.raises(JournalFlushError) as excinfo, s.transaction():
            s.set("a", 1)
            s.set("b", 2)
            s.set("c", 3)

        message = str(excinfo.value)
        assert "transaction committed, but 2 journal events failed to flush" in message
        assert "data is durable" in message

        # the data really is committed: a second connection sees all of it
        conn = sqlite3.connect(str(db))
        try:
            rows = dict(conn.execute("SELECT key, value FROM kv").fetchall())
        finally:
            conn.close()
        assert rows == {"a": "1", "b": "2", "c": "3"}

        # one bad event does not stop the rest, and nothing is left to retry
        assert [e.payload["key"] for e in journal.events] == ["a"]
        assert s._journal_buffer == []
    finally:
        s.close()
