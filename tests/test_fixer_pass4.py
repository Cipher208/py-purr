"""Fixer tests, заход 4: a failed write must not leave an open transaction behind.

mset() and set() mutate the connection and then fall over (unserializable
value, ttl overflow) without rolling back: the half-written rows sit in an
open transaction and the next unrelated commit() makes them durable.
"""

import pytest

from purr import Store


def test_mset_failure_rolls_back_uncommitted_keys(tmp_path):
    """A TypeError midway through mset() must leave no uncommitted rows."""
    db = tmp_path / "store.db"
    s = Store(db)
    try:
        with pytest.raises(TypeError):
            s.mset({"good": 1, "bad": object()})

        # nothing half-applied, and no transaction left holding a write lock
        assert s._get_conn().in_transaction is False
        assert s.keys() == []
        assert s.size() == 0
        assert s.get("good") is None

        # the next write starts from a clean slate and commits only its own data
        s.set("real", 1)
        s.mset({"other": 2})
        assert sorted(s.keys()) == ["other", "real"]
    finally:
        s.close()

    reopen = Store(db)
    try:
        # the failed keys were not resurrected by a later commit
        assert sorted(reopen.keys()) == ["other", "real"]
        assert reopen.get("good") is None
    finally:
        reopen.close()


def test_set_ttl_overflow_rolls_back(tmp_path):
    """set() failing after the INSERT (huge ttl) must not keep the row."""
    s = Store(tmp_path / "store.db")
    try:
        with pytest.raises(OSError):
            s.set("k", 1, ttl=1e18)

        assert s._get_conn().in_transaction is False
        assert s.get("k") is None
        assert s.keys() == []
    finally:
        s.close()
