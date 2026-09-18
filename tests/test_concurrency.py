"""Writer-contention contract: every connection waits on locked DB (H1-2)."""
from purr import EventStream, StateMachine, Store

BUSY_TIMEOUT_MS = 5000


def test_store_busy_timeout(tmp_path):
    s = Store(tmp_path / "t.db")
    row = s._get_conn().execute("PRAGMA busy_timeout").fetchone()
    assert row[0] == BUSY_TIMEOUT_MS
    s.close()


def test_state_machine_busy_timeout(tmp_path):
    sm = StateMachine("m", db_path=tmp_path / "t.db")
    row = sm._get_conn().execute("PRAGMA busy_timeout").fetchone()
    assert row[0] == BUSY_TIMEOUT_MS
    sm.close()


def test_event_stream_busy_timeout(tmp_path):
    es = EventStream(tmp_path / "t.db")
    row = es._get_conn().execute("PRAGMA busy_timeout").fetchone()
    assert row[0] == BUSY_TIMEOUT_MS
    es.close()
