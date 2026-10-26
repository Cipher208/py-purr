"""P1-fix tests for Store: transaction flag poisoning, per-thread txn flag, atomic incr."""

import sqlite3
import threading
import time

import pytest

from purr import Store


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "test.db")


class _FlakyConn:
    """Proxy that fails the first BEGIN IMMEDIATE, then delegates."""

    def __init__(self, conn):
        self._conn = conn
        self.fail_next_begin = True

    def execute(self, sql, *args, **kwargs):
        if self.fail_next_begin and "BEGIN" in sql:
            self.fail_next_begin = False
            raise sqlite3.OperationalError("database is locked")
        return self._conn.execute(sql, *args, **kwargs)

    def commit(self):
        return self._conn.commit()

    def rollback(self):
        return self._conn.rollback()


class TestP1_1TransactionFlagReset:
    def test_transaction_flag_reset_on_begin_failure(self, tmp_path, monkeypatch):
        s = Store(tmp_path / "t.db")
        proxy = _FlakyConn(s._get_conn())
        monkeypatch.setattr(s, "_get_conn", lambda: proxy)

        with (
            pytest.raises(sqlite3.OperationalError, match="database is locked"),
            s.transaction(),
        ):
            pass  # pragma: no cover

        # flag must be reset, not poisoned
        assert s._in_transaction is False

        # subsequent transaction() works and set() commits durably
        with s.transaction():
            s.set("a", 1)
        s.close()

        s2 = Store(tmp_path / "t.db")
        assert s2.get("a") == 1
        s2.close()


class TestP1_2PerThreadTransactionFlag:
    def test_concurrent_transactions_two_threads(self, tmp_path):
        s = Store(tmp_path / "t.db")
        errors: list[Exception] = []
        inside_txn = threading.Event()

        def worker1() -> None:
            try:
                with s.transaction():
                    s.set("a", "a")
                    inside_txn.set()
                    time.sleep(0.3)  # keep txn open briefly so thread2 enters while flag is set
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        def worker2() -> None:
            try:
                inside_txn.wait(timeout=5)
                with s.transaction():
                    s.set("b", "b")
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        threads = [threading.Thread(target=worker1), threading.Thread(target=worker2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        assert s.get("a") == "a"
        assert s.get("b") == "b"
        s.close()


class TestP1_3AtomicIncr:
    def test_incr_concurrent_threads(self, tmp_path):
        s = Store(tmp_path / "t.db")
        n_threads, n_incr = 4, 200
        errors: list[Exception] = []
        barrier = threading.Barrier(n_threads)

        def worker() -> None:
            try:
                barrier.wait()
                for _ in range(n_incr):
                    s.incr("ctr")
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        assert s.get("ctr") == n_threads * n_incr
        s.close()


class TestP1_4IncrExpiry:
    def test_incr_expired_key_resurrects(self, store):
        store.set("ctr", 100, ttl=0.2)
        import time

        time.sleep(0.4)
        assert store.incr("ctr") == 1  # Redis semantics: amount, not old+1
        assert store.get("ctr") == 1

    def test_incr_preserves_ttl(self, store):
        store.set("k", 10, ttl=60)
        store.incr("k")
        remaining = store.ttl("k")
        assert remaining is not None and remaining > 0


class TestMgetExpiryGuard:
    """Guard test (not a red test): mget must skip expired keys via get()."""

    def test_mget_skips_expired(self, store):
        store.set("live", 1)
        store.set("dead", 2, ttl=-10)
        assert store.mget(["live", "dead"]) == [1, None]
        assert store.get("dead") is None
