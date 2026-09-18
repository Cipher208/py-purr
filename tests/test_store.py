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


class TestStoreAtomic:
    def test_mset(self, store):
        store.mset({"a": 1, "b": 2, "c": 3})
        assert store.mget(["a", "b", "c"]) == [1, 2, 3]

    def test_mget(self, store):
        store.set("a", 1)
        store.set("b", 2)
        assert store.mget(["a", "b", "missing"]) == [1, 2, None]


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
