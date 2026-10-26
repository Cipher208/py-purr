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
    SCHEMA_VERSION = 1
    ENGINE_NAME = ""
    MIGRATIONS: dict[int, str] = {}

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)
        self._local = threading.local()
        self._init_db()

    def _init_db(self) -> None:
        """Create schema. Subclasses implement with their own DDL."""

    def run_migrations(self) -> int:
        """Apply pending MIGRATIONS in order. Returns applied count.

        Version tracking is per-engine via the _purr_schema registry table
        (engine TEXT PRIMARY KEY, version INTEGER NOT NULL), because
        PRAGMA user_version is a single counter per database FILE, not per
        engine: two engines sharing one file would otherwise skip each
        other's migrations ("no such table" on the second engine).

        Legacy databases (user_version > 0, no registry row for this
        engine): which engine owned user_version is unknowable, so ALL of
        this engine's migrations are re-applied idempotently (the DDL uses
        IF NOT EXISTS) and the engine registers at its SCHEMA_VERSION.

        PRAGMA user_version is still kept (raised to the max applied
        version) for older-tooling compatibility.

        Opening an already-migrated database performs no writes at all: the
        registry row and user_version are only written when migrations are
        pending or user_version still needs clamping. Before this, every open
        ran CREATE TABLE IF NOT EXISTS + INSERT OR REPLACE, so a read-only
        database failed with "attempt to write a readonly database" and a
        database held by another writer blocked on the busy timeout.
        """
        conn = self._get_conn()
        engine = self.ENGINE_NAME or type(self).__name__
        try:
            row = conn.execute(
                "SELECT version FROM _purr_schema WHERE engine = ?", (engine,)
            ).fetchone()
        except sqlite3.OperationalError as exc:
            # Registry table not created yet (fresh file, or legacy db).
            if "no such table" not in str(exc):
                raise
            row = None
        user_version = conn.execute("PRAGMA user_version").fetchone()[0] or 0
        if row is None:
            # No registry row: fresh engine, or legacy file (user_version > 0)
            # where the engine's true version is unknowable — apply all
            # migrations idempotently.
            pending = sorted(self.MIGRATIONS)
        else:
            pending = [v for v in sorted(self.MIGRATIONS) if v > row[0]]
        if not pending and user_version >= (row[0] if row else 0):
            # Up to date and nothing to clamp: stay silent so the open works
            # on a read-only file and does not need a write lock at all.
            return 0
        applied = 0
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS _purr_schema"
                " (engine TEXT PRIMARY KEY, version INTEGER NOT NULL)"
            )
            for version in pending:
                conn.executescript(self.MIGRATIONS[version])
                applied += 1
            registered = max(pending) if pending else (row[0] if row else 0)
            conn.execute(
                "INSERT OR REPLACE INTO _purr_schema (engine, version) VALUES (?, ?)",
                (engine, registered),
            )
            if registered < self.SCHEMA_VERSION:
                registered = self.SCHEMA_VERSION
            if user_version < registered:
                conn.execute(f"PRAGMA user_version={registered}")
            conn.commit()
        except sqlite3.OperationalError:
            with contextlib.suppress(sqlite3.Error):
                conn.rollback()
            if pending:
                # Schema really is behind: the caller must not run unmatched.
                raise
            # Only the registry/clamp bookkeeping was rejected (read-only file,
            # another writer holds the lock). The schema is already in place,
            # so opening can continue.
        return applied

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
