"""Fixer tests (general-purpose-2): store performance, pragmas, retry, health.

One class per fix cycle; each test states the defect it pins.
"""

from __future__ import annotations

from purr import Store


class _SqlLog:
    """Collect every statement the store's connection executes."""

    def __init__(self, store: Store) -> None:
        self.conn = store._get_conn()
        self.statements: list[str] = []

    def __enter__(self) -> _SqlLog:
        self.conn.set_trace_callback(self.statements.append)
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.conn.set_trace_callback(None)

    @property
    def body(self) -> list[str]:
        """Statements minus transaction control (COMMIT/BEGIN/ROLLBACK)."""
        control = {"COMMIT", "BEGIN", "BEGIN IMMEDIATE", "ROLLBACK", "END"}
        return [s for s in self.statements if s.strip().upper() not in control]


class TestCycle1SetSingleStatement:
    """set() probed the key with a SELECT and re-SELECTed created_at in the INSERT."""

    def test_set_returns_created_flag_and_preserves_created_at(self, tmp_path):
        store = Store(tmp_path / "s.db")
        try:
            assert store.set("k", "first") is True
            created_at = (
                store._get_conn().execute("SELECT created_at FROM kv WHERE key = 'k'").fetchone()[0]
            )

            assert store.set("k", "second") is False
            after = (
                store._get_conn()
                .execute("SELECT created_at, value FROM kv WHERE key = 'k'")
                .fetchone()
            )
            assert after["created_at"] == created_at, "overwrite must keep created_at"
            assert after["value"] == '"second"'
        finally:
            store.close()

    def test_set_does_not_probe_key_with_select(self, tmp_path):
        """A plain set() must not need a separate existence SELECT.

        Pre-fix every set() ran `SELECT key FROM kv WHERE key = ?` and then
        `COALESCE((SELECT created_at FROM kv WHERE key = ?), ?)` inside the
        INSERT — two extra index lookups per write.
        """
        store = Store(tmp_path / "s.db")
        try:
            for _ in range(2):  # create, then overwrite
                with _SqlLog(store) as log:
                    store.set("k", "v")
                selects = [s for s in log.body if s.lstrip().upper().startswith("SELECT")]
                assert selects == [], f"set() still probes with SELECT: {log.body}"
                assert len([s for s in log.body if "INSERT" in s.upper()]) == 1, log.body
        finally:
            store.close()

    def test_set_statement_count_is_bounded(self, tmp_path):
        """set() must stay at two statements: the write plus the TTL cleanup."""
        store = Store(tmp_path / "s.db")
        try:
            with _SqlLog(store) as log:
                store.set("k", "v")
            assert len(log.body) == 2, log.body
        finally:
            store.close()
