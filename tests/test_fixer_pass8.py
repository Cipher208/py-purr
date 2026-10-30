"""Fixer pass 8 — batch mget, expiry index, foreign keys, pragmas, retry, health, KEYS.

One class per cycle; each test states the defect it pins.
"""

from __future__ import annotations

import random
import sqlite3
import time

import pytest

from purr import EventStream, Store
from purr.health import HealthChecker, HealthStatus
from purr.retry import RetryConfig, RetryHandler
from purr.state_machine import StateMachine

from .test_fixer_perf_pragmas import _SqlLog


class TestCycle1BatchMget:
    """mget() issued 2 queries per key (`[self.get(key) for key in keys]`)."""

    def test_mget_matches_get_semantics(self, tmp_path):
        """Lives, expired and missing keys must answer exactly like get().

        Reading is not writing: an expired key answers as missing, but its row
        stays in kv and kv_meta and no delete event is journalled. Physical
        removal belongs to sweep()/maintain().
        """
        db = tmp_path / "s.db"
        journal = EventStream(db)
        store = Store(db, journal=journal)
        try:
            store.set("live:1", {"n": 1})
            store.set("live:2", "two")
            store.set("dead:1", "gone", ttl=-1)
            store.set("dead:2", [1, 2], ttl=-1)
            keys = ["live:1", "missing", "dead:1", "live:2", "dead:2", "live:1"]
            before, _ = journal.read()

            result = store.mget(keys)

            assert result == [{"n": 1}, None, None, "two", None, {"n": 1}], (
                "mget must equal [get(k) for k in keys], order and duplicates kept"
            )
            assert result == [store.get(k) for k in keys]

            after, _ = journal.read()
            deletes = [
                event.payload["key"]
                for event in after[len(before) :]
                if event.payload.get("op") == "delete"
            ]
            assert deletes == [], f"mget must not delete expired keys, journalled: {deletes}"

            conn = store._get_conn()
            for dead in ("dead:1", "dead:2"):
                assert (
                    conn.execute("SELECT COUNT(*) FROM kv WHERE key = ?", (dead,)).fetchone()[0]
                    == 1
                ), f"{dead} must stay in kv: reading is not sweeping"
                assert (
                    conn.execute("SELECT COUNT(*) FROM kv_meta WHERE key = ?", (dead,)).fetchone()[
                        0
                    ]
                    == 1
                ), f"{dead} must stay in kv_meta: reading is not sweeping"
            assert store.get("live:1") == {"n": 1}, "live keys must survive"
        finally:
            store.close()
            journal.close()

    def test_mget_empty_list_runs_no_queries(self, tmp_path):
        store = Store(tmp_path / "s.db")
        try:
            with _SqlLog(store) as log:
                assert store.mget([]) == []
            assert log.body == [], log.body
        finally:
            store.close()

    def test_mget_query_count_is_constant(self, tmp_path):
        """The whole batch costs two statements, not two per key."""
        store = Store(tmp_path / "s.db")
        try:
            store.mset({f"k{i}": i for i in range(50)})
            with _SqlLog(store) as log:
                store.mget([f"k{i}" for i in range(50)])
            selects = [s for s in log.statements if s.lstrip().upper().startswith("SELECT")]
            assert len(selects) == 2, log.statements
        finally:
            store.close()

    def test_mget_1000_keys_is_faster_than_per_key_get(self, tmp_path):
        """Timing record for the batch rewrite (1000 keys, temp db)."""
        store = Store(tmp_path / "s.db")
        try:
            keys = [f"k{i}" for i in range(1000)]
            store.mset({k: i for i, k in enumerate(keys)})
            store.mget(keys)  # warm

            start = time.perf_counter()
            store.mget(keys)
            batch_ms = (time.perf_counter() - start) * 1000

            start = time.perf_counter()
            [store.get(k) for k in keys]
            per_key_ms = (time.perf_counter() - start) * 1000

            assert batch_ms < per_key_ms / 2, (
                f"mget {batch_ms:.2f} ms vs per-key get {per_key_ms:.2f} ms"
            )
        finally:
            store.close()


class TestCycle2ExpiresIndex:
    """sweep() scanned kv_meta: expires_at had no index."""

    SWEEP_SQL = "SELECT key FROM kv_meta WHERE expires_at IS NOT NULL AND expires_at <= ?"

    def test_sweep_uses_expires_index(self, tmp_path):
        store = Store(tmp_path / "s.db")
        try:
            conn = store._get_conn()
            indexes = [row[1] for row in conn.execute("PRAGMA index_list(kv_meta)")]
            assert "idx_kv_meta_expires" in indexes, indexes

            plan = [row[3] for row in conn.execute(f"EXPLAIN QUERY PLAN {self.SWEEP_SQL}", ("x",))]
            assert any("USING INDEX idx_kv_meta_expires" in step for step in plan), plan
        finally:
            store.close()

    def test_existing_v1_database_is_migrated_in_place(self, tmp_path):
        """A version-1 file must gain the index without its tables being recreated."""
        db = tmp_path / "legacy.db"
        conn = sqlite3.connect(str(db))
        try:
            conn.executescript(
                Store.MIGRATIONS[1]
                + """
                CREATE TABLE _purr_schema (engine TEXT PRIMARY KEY, version INTEGER NOT NULL);
                INSERT INTO _purr_schema (engine, version) VALUES ('store', 1);
                PRAGMA user_version=1;
                INSERT INTO kv (key, value, type, created_at, updated_at)
                    VALUES ('keep', '"me"', 'str', '2026-01-01T00:00:00+00:00',
                            '2026-01-01T00:00:00+00:00');
                """
            )
            conn.commit()
        finally:
            conn.close()

        store = Store(db)
        try:
            assert Store.SCHEMA_VERSION == 2
            assert store.get("keep") == "me", "migration must not recreate tables"
            conn = store._get_conn()
            assert (
                conn.execute("SELECT version FROM _purr_schema WHERE engine = 'store'").fetchone()[
                    0
                ]
                == 2
            )
            assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
            assert "idx_kv_meta_expires" in [
                row[1] for row in conn.execute("PRAGMA index_list(kv_meta)")
            ]
        finally:
            store.close()


class TestCycle3ForeignKeys:
    """The schema declares FKs but `PRAGMA foreign_keys` stayed 0."""

    def test_foreign_keys_enforced(self, tmp_path):
        store = Store(tmp_path / "s.db")
        try:
            conn = store._get_conn()
            assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute("INSERT INTO kv_meta (key, expires_at) VALUES ('ghost', NULL)")
            conn.rollback()
            assert store.set("real", 1) is True
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute("INSERT INTO kv_meta (key, expires_at) VALUES ('ghost', NULL)")
            conn.rollback()
        finally:
            store.close()

    def test_orphans_cleaned_on_open(self, tmp_path):
        """Orphans written while enforcement was off must not break the open."""
        db = tmp_path / "s.db"
        Store(db).close()

        raw = sqlite3.connect(str(db))
        try:
            assert raw.execute("PRAGMA foreign_keys").fetchone()[0] == 0
            raw.executescript(
                """
                INSERT INTO kv_meta (key, expires_at) VALUES ('ghost', NULL);
                INSERT INTO kv_meta (key, expires_at) VALUES ('phantom', NULL);
                """
            )
            raw.commit()
        finally:
            raw.close()

        store = Store(db)
        try:
            conn = store._get_conn()
            assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
            orphans = conn.execute(
                "SELECT key FROM kv_meta WHERE key IN ('ghost', 'phantom')"
            ).fetchall()
            assert [row[0] for row in orphans] == [], "orphan kv_meta rows must be removed"
            assert store.set("after", "ok") is True, "open must leave a usable store"
        finally:
            store.close()

    def test_orphan_snapshot_cleaned_on_open(self, tmp_path):
        """Cleanup is driven by the schema, not by a hard-coded store FK list."""
        db = tmp_path / "shared.db"
        Store(db).close()
        StateMachine("m1", db).close()

        raw = sqlite3.connect(str(db))
        try:
            raw.execute("PRAGMA foreign_keys=OFF")
            raw.execute(
                "INSERT INTO state_snapshots (machine_name, state, data, created_at)"
                " VALUES ('never-existed', 's', '{}', '2026-01-01T00:00:00+00:00')"
            )
            raw.commit()
        finally:
            raw.close()

        Store(db).close()
        check = sqlite3.connect(str(db))
        try:
            assert check.execute("SELECT COUNT(*) FROM state_snapshots").fetchone()[0] == 0
        finally:
            check.close()


class TestCycle4PragmaTuning:
    """Default tuning: 2 MB cache, no mmap, file-backed temp store, endless WAL."""

    def test_pragma_tuning_applied(self, tmp_path):
        store = Store(tmp_path / "s.db")
        try:
            conn = store._get_conn()
            raw = {
                name: conn.execute(f"PRAGMA {name}").fetchone()[0]
                for name in ("cache_size", "mmap_size", "temp_store", "journal_size_limit")
            }
            assert raw["cache_size"] == -16000, raw
            assert raw["mmap_size"] == 268435456, raw
            assert raw["temp_store"] == 2, f"2 == MEMORY: {raw}"
            assert raw["journal_size_limit"] == 67108864, raw
            # Untouched by this cycle: durability contract stays as it was.
            assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
            assert conn.execute("PRAGMA synchronous").fetchone()[0] == 1
        finally:
            store.close()

    def test_maintain_truncates_the_wal(self, tmp_path):
        store = Store(tmp_path / "s.db")
        try:
            for i in range(2000):
                store.set(f"k{i}", i)
            report = store.maintain()
            assert report["checkpoint"] == "ok", report
            assert report["wal_bytes"] <= 67108864, report
        finally:
            store.close()


class TestCycle5RetryClamp:
    """Jitter was applied after the clamp, so the real ceiling was 1.5x max_delay."""

    def test_backoff_never_exceeds_max_delay(self):
        config = RetryConfig(base_delay=1.0, max_delay=5.0, max_retries=10)
        handler = RetryHandler(config)
        random.seed(20261026)

        delays = [handler._calculate_delay(attempt) for attempt in range(1, 201)]

        assert max(delays) <= config.max_delay, f"max delay {max(delays)} exceeded ceiling"
        assert all(delay >= 0 for delay in delays)
        # Jitter must still be alive: a clamped ceiling alone would be flat.
        capped = [delay for delay in delays if delay == config.max_delay]
        assert capped, "no attempt reached the ceiling"
        assert len(set(delays)) > 1, "jitter collapsed to a constant"

    def test_jitter_range_is_half_to_one_and_a_half(self):
        """Jitter multiplies by 0.5..1.5 — the ceiling is what must not move."""
        config = RetryConfig(base_delay=1.0, max_delay=60.0, jitter=True)
        handler = RetryHandler(config)
        random.seed(7)

        delays = [handler._calculate_delay(1) for _ in range(200)]

        assert all(0.5 <= delay <= 1.5 for delay in delays), (min(delays), max(delays))
        assert max(delays) > 1.2 and min(delays) < 0.8, "jitter is not spread"

    def test_jitter_disabled_is_plain_backoff(self):
        handler = RetryHandler(RetryConfig(base_delay=2.0, max_delay=5.0, jitter=False))
        assert [handler._calculate_delay(attempt) for attempt in range(1, 5)] == [
            2.0,
            4.0,
            5.0,
            5.0,
        ]

    def test_no_dead_pending_state(self):
        assert not hasattr(RetryHandler(), "_pending")


class TestCycle6HealthNonBool:
    """A check returning a string or None left the status silently unchanged."""

    def test_non_bool_result_marked_unhealthy(self):
        checker = HealthChecker()
        checker.register("db", lambda: "ok")

        assert checker.check("db") == HealthStatus.UNHEALTHY
        error = checker.get_status()["components"]["db"]["error"]
        assert "str" in error and "expected bool or HealthStatus" in error, error

    def test_bool_results_still_map_to_status(self):
        checker = HealthChecker()
        checker.register("up", lambda: True)
        checker.register("down", lambda: False)

        assert checker.check("up") == HealthStatus.HEALTHY
        assert checker.check("down") == HealthStatus.UNHEALTHY
        assert checker.get_status()["components"]["up"]["error"] == ""

    def test_health_status_result_passes_through(self):
        checker = HealthChecker()
        checker.register("slow", lambda: HealthStatus.DEGRADED)

        assert checker.check("slow") == HealthStatus.DEGRADED

    def test_none_result_names_the_type(self):
        checker = HealthChecker()
        checker.register("void", lambda: None)

        assert checker.check("void") == HealthStatus.UNHEALTHY
        assert "NoneType" in checker.get_status()["components"]["void"]["error"]


class TestCycle7KeyPatternCase:
    """keys() matched LIKE case-insensitively, unlike Redis KEYS."""

    def test_keys_is_case_sensitive(self, tmp_path):
        store = Store(tmp_path / "s.db")
        try:
            store.set("USER:1", "a")
            store.set("user:2", "b")
            store.set("UseR:3", "c")

            assert store.keys("USER:*") == ["USER:1"]
            assert store.keys("user:*") == ["user:2"]
            assert sorted(store.keys("*")) == ["USER:1", "UseR:3", "user:2"]
        finally:
            store.close()

    def test_keys_report_pattern_does_not_hit_everything(self, tmp_path):
        """Case sensitivity is a real filter, not a substring accident."""
        store = Store(tmp_path / "s.db")
        try:
            store.set("cache:Home", 1)
            store.set("cache:home", 2)

            assert store.keys("cache:h*") == ["cache:home"]
        finally:
            store.close()
