"""Tests for PURR Store."""

import pytest

from purr import Store


@pytest.fixture
def store(tmp_path):
    """Create a temporary store."""
    return Store(tmp_path / "test.db")


class TestStoreBasic:
    def test_set_get(self, store):
        store.set("key", "value")
        assert store.get("key") == "value"

    def test_get_missing(self, store):
        assert store.get("missing") is None

    def test_delete(self, store):
        store.set("key", "value")
        assert store.delete("key") is True
        assert store.get("key") is None

    def test_delete_missing_returns_false(self, store):
        store.set("key", "value")
        assert store.delete("ghost") is False

    def test_exists(self, store):
        store.set("key", "value")
        assert store.exists("key") is True
        assert store.exists("missing") is False

    def test_keys(self, store):
        store.set("a", 1)
        store.set("b", 2)
        store.set("c", 3)
        keys = store.keys()
        assert sorted(keys) == ["a", "b", "c"]

    def test_keys_pattern(self, store):
        store.set("user:1", "alice")
        store.set("user:2", "bob")
        store.set("post:1", "hello")
        keys = store.keys("user:*")
        assert sorted(keys) == ["user:1", "user:2"]

    def test_keys_pattern_treats_underscore_literally(self, store):
        store.set("user_1", "alice")
        store.set("userX1", "bob")
        assert store.keys("user_1") == ["user_1"]

    def test_flush(self, store):
        store.set("a", 1)
        store.set("b", 2)
        assert store.flush() == 2
        assert store.size() == 0

    def test_size(self, store):
        assert store.size() == 0
        store.set("a", 1)
        assert store.size() == 1


class TestStoreTypes:
    def test_string(self, store):
        store.set("key", "hello")
        assert store.get("key") == "hello"

    def test_int(self, store):
        store.set("key", 42)
        assert store.get("key") == 42

    def test_float(self, store):
        store.set("key", 3.14)
        assert store.get("key") == 3.14

    def test_bool(self, store):
        store.set("key", True)
        assert store.get("key") is True

    def test_list(self, store):
        store.set("key", [1, 2, 3])
        assert store.get("key") == [1, 2, 3]

    def test_dict(self, store):
        store.set("key", {"a": 1, "b": 2})
        assert store.get("key") == {"a": 1, "b": 2}

    def test_none(self, store):
        store.set("key", None)
        assert store.get("key") is None


class TestStoreTTL:
    def test_ttl_no_expiry(self, store):
        store.set("key", "value")
        assert store.ttl("key") is None

    def test_ttl_with_expiry(self, store):
        store.set("key", "value", ttl=60)
        ttl = store.ttl("key")
        assert ttl is not None
        assert 55 <= ttl <= 60

    def test_expire(self, store):
        store.set("key", "value")
        assert store.expire("key", 60) is True
        ttl = store.ttl("key")
        assert ttl is not None

    def test_expire_nonexistent(self, store):
        assert store.expire("missing", 60) is False


class TestStoreSweep:
    def test_sweep_removes_expired(self, store):
        store.set("fresh", 1, ttl=60)
        store.set("dead", 2, ttl=-10)
        assert store.size() == 2
        assert store.sweep() == 1
        assert store.size() == 1
        assert store.get("fresh") == 1

    def test_maintain_reports(self, store):
        store.set("fresh", 1, ttl=60)
        store.set("dead", 2, ttl=-10)
        report = store.maintain()
        assert report["swept"] == 1
        assert report["keys"] == 1
        assert report["integrity"] == "ok"
        assert report["db_bytes"] > 0


class TestStoreAtomic:
    def test_mset(self, store):
        store.mset({"a": 1, "b": 2, "c": 3})
        assert store.mget(["a", "b", "c"]) == [1, 2, 3]

    def test_mget(self, store):
        store.set("a", 1)
        store.set("b", 2)
        assert store.mget(["a", "b", "missing"]) == [1, 2, None]


class TestStoreTransaction:
    def test_commit_on_clean_exit(self, store):
        with store.transaction():
            store.set("a", 1)
            store.set("b", 2)
        assert store.mget(["a", "b"]) == [1, 2]

    def test_commit_persists_across_reopen(self, tmp_path):
        from purr import Store as S2

        db = tmp_path / "t.db"
        s = S2(db)
        with s.transaction():
            s.set("a", 1)
        s.close()
        s2 = S2(db)
        assert s2.get("a") == 1
        s2.close()

    def test_rollback_on_error(self, store):
        with pytest.raises(RuntimeError, match="boom"), store.transaction():
            store.set("a", 1)
            raise RuntimeError("boom")
        assert store.get("a") is None


class TestStoreNumeric:
    def test_incr(self, store):
        store.set("counter", 0)
        assert store.incr("counter") == 1
        assert store.incr("counter") == 2
        assert store.incr("counter", 5) == 7

    def test_incr_new(self, store):
        assert store.incr("counter") == 1

    def test_decr(self, store):
        store.set("counter", 10)
        assert store.decr("counter") == 9
        assert store.decr("counter", 3) == 6

    def test_incr_non_numeric(self, store):
        store.set("key", "not a number")
        with pytest.raises(TypeError):
            store.incr("key")

    def test_incr_float_keeps_fraction(self, store):
        store.set("price", 2.5)
        assert store.incr("price", 1) == 3.5
        assert store.get("price") == 3.5


class TestStoreJournal:
    def test_mutations_appended_to_journal(self, tmp_path):
        from purr import EventStream

        es = EventStream(tmp_path / "j.db")
        s = Store(tmp_path / "s.db", journal=es)
        s.set("a", 1)
        s.expire("a", 60)
        s.delete("a")
        events, _ = es.read(topic="store")
        assert [(e.payload["op"], e.payload.get("key")) for e in events] == [
            ("set", "a"),
            ("expire", "a"),
            ("delete", "a"),
        ]
        s.close()
        es.close()

    def test_journal_replays_to_final_state(self, tmp_path):
        from purr import EventStream

        es = EventStream(tmp_path / "j.db")
        s = Store(tmp_path / "s.db", journal=es)
        s.set("a", 1)
        s.set("b", 2)
        s.delete("a")
        state: dict = {}
        events, _ = es.read(topic="store")
        for e in events:
            if e.payload["op"] == "delete":
                state.pop(e.payload["key"], None)
            else:
                state[e.payload["key"]] = e.payload["value"]
        assert state == {"b": 2}
        s.close()
        es.close()

    def test_no_journal_no_stream_writes(self, tmp_path):
        from purr import EventStream

        es = EventStream(tmp_path / "j.db")
        s = Store(tmp_path / "s.db")
        s.set("a", 1)
        events, _ = es.read(topic="store")
        assert events == []
        s.close()
        es.close()

    def test_journal_flushes_on_txn_commit(self, tmp_path):
        from purr import EventStream

        es = EventStream(tmp_path / "j.db")
        s = Store(tmp_path / "s.db", journal=es)
        with s.transaction():
            s.set("a", 1)
            events_during, _ = es.read(topic="store")
            assert events_during == []
        events, _ = es.read(topic="store")
        assert [e.payload["key"] for e in events] == ["a"]
        s.close()
        es.close()

    def test_journal_drops_on_txn_rollback(self, tmp_path):
        from purr import EventStream

        es = EventStream(tmp_path / "j.db")
        s = Store(tmp_path / "s.db", journal=es)
        with pytest.raises(RuntimeError, match="boom"), s.transaction():
            s.set("a", 1)
            raise RuntimeError("boom")
        events, _ = es.read(topic="store")
        assert events == []
        s.close()
        es.close()
