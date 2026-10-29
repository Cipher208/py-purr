"""Fixer pass 7 — a failed migration must not leave partial DDL behind."""

import sqlite3

import pytest

from purr.backend import SQLiteBackend


class _BrokenMigrationEngine(SQLiteBackend):
    """Second statement collides with the first, so the script fails midway."""

    ENGINE_NAME = "broken_partial"
    SCHEMA_VERSION = 1
    MIGRATIONS = {1: "CREATE TABLE orphan (id INTEGER); CREATE TABLE orphan (id INTEGER);"}

    def _init_db(self) -> None:
        self.run_migrations()


def test_failed_migration_leaves_no_partial_ddl(tmp_path):
    """executescript() committed each statement, so the first CREATE survived.

    The failed migration left table `orphan` behind while the registry stayed
    empty — and re-running the same non-idempotent script could never succeed,
    leaving the database permanently unopenable.
    """
    db = tmp_path / "broken.db"
    with pytest.raises(sqlite3.OperationalError, match="already exists"):
        _BrokenMigrationEngine(db)

    conn = sqlite3.connect(str(db))
    try:
        tables = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert "orphan" not in tables
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 0
        registry = conn.execute(
            "SELECT version FROM _purr_schema WHERE engine='broken_partial'"
        ).fetchall()
        assert registry == []
    finally:
        conn.close()
