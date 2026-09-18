"""PURR SQLiteBackend — shared connection lifecycle for all engines.

One connection per thread per instance (instance isolation contract);
pragmas, checkpoint, integrity, backup and stats live here once.
"""

from __future__ import annotations

import contextlib
import sqlite3
import threading
from pathlib import Path
from typing import Any


class SQLiteBackend:
    """Base for file-backed engines sharing one SQLite database file."""

    BUSY_TIMEOUT_MS = 5000

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)
        self._local = threading.local()
        self._init_db()

    def _init_db(self) -> None:
        """Create schema. Subclasses implement with their own DDL."""

    def _get_conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(str(self._db_path))
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.execute("PRAGMA synchronous=NORMAL")
            # Explicit writer-wait contract: do not rely on the driver default.
            self._local.conn.execute(f"PRAGMA busy_timeout={self.BUSY_TIMEOUT_MS}")
            self._local.conn.row_factory = sqlite3.Row
        return self._local.conn

    def close(self) -> None:
        """Close the connection for this thread."""
        if hasattr(self._local, "conn") and self._local.conn is not None:
            with contextlib.suppress(Exception):
                self._local.conn.close()
            self._local.conn = None

    def checkpoint(self) -> str:
        """Checkpoint the WAL. Returns ok/busy."""
        row = self._get_conn().execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        return "ok" if row and row[0] == 0 else "busy"

    def integrity(self) -> str:
        """Integrity check. Returns ok or the first problem."""
        row = self._get_conn().execute("PRAGMA integrity_check").fetchone()
        return "ok" if row and row[0] == "ok" else str(row[0] if row else "unknown")

    def backup(self, dest: str | Path) -> None:
        """Crash-safe snapshot of the database file."""
        self._get_conn().execute("VACUUM INTO ?", (str(dest),))

    def db_stats(self) -> dict[str, Any]:
        """File sizes in bytes. Zeroes for in-memory databases."""
        if str(self._db_path) == ":memory:":
            return {"db_bytes": 0, "wal_bytes": 0}
        db = self._db_path.stat().st_size if self._db_path.exists() else 0
        wal = self._db_path.with_suffix(".db-wal")
        wal_bytes = wal.stat().st_size if wal.exists() else 0
        return {"db_bytes": db, "wal_bytes": wal_bytes}
