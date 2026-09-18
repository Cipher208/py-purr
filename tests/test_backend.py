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
