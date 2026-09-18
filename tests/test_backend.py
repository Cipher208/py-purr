"""SQLiteBackend contract: shared connection lifecycle for all engines (A1)."""

from purr.backend import SQLiteBackend


class Tiny(SQLiteBackend):
    def _init_db(self):
        self._get_conn().execute("CREATE TABLE IF NOT EXISTS t (id INTEGER)").connection.commit()


def test_backend_applies_pragmas(tmp_path):
    b = Tiny(tmp_path / "b.db")
    row = b._get_conn().execute("PRAGMA journal_mode").fetchone()
    assert row[0].lower() == "wal"
    assert b._get_conn().execute("PRAGMA busy_timeout").fetchone()[0] == 5000
    b.close()


def test_backend_checkpoint_and_integrity(tmp_path):
    b = Tiny(tmp_path / "b.db")
    assert b.integrity() == "ok"
    assert b.checkpoint() in ("ok", "busy", "notidle")
    b.close()


def test_backend_backup(tmp_path):
    src = tmp_path / "b.db"
    dst = tmp_path / "copy.db"
    b = Tiny(src)
    b.backup(dst)
    assert dst.exists() and dst.stat().st_size > 0
    b.close()


def test_backend_stats(tmp_path):
    b = Tiny(tmp_path / "b.db")
    stats = b.db_stats()
    assert stats["db_bytes"] > 0
    assert "wal_bytes" in stats
    b.close()


class Mig(SQLiteBackend):
    SCHEMA_VERSION = 2
    MIGRATIONS = {
        1: "CREATE TABLE IF NOT EXISTS m1 (id INTEGER);",
        2: "CREATE TABLE IF NOT EXISTS m2 (id INTEGER);",
    }

    def _init_db(self):
        self.run_migrations()


def test_migrations_run_to_latest(tmp_path):
    m = Mig(tmp_path / "m.db")
    conn = m._get_conn()
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"m1", "m2"} <= tables
    m.close()


def test_migrations_idempotent_and_legacy_safe(tmp_path):
    db = tmp_path / "m.db"
    Mig(db).close()
    m2 = Mig(db)
    assert m2._get_conn().execute("PRAGMA user_version").fetchone()[0] == 2
    m2.close()
    import sqlite3

    legacy = sqlite3.connect(str(db))
    legacy.execute("PRAGMA user_version=0")
    legacy.commit()
    legacy.close()
    m3 = Mig(db)
    assert m3._get_conn().execute("PRAGMA user_version").fetchone()[0] == 2
    m3.close()
