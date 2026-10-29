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
        IF NOT EXISTS) and the engine registers at the highest applied
        migration.

        The registry row and PRAGMA user_version always hold the same value:
        the highest applied migration, capped at SCHEMA_VERSION. SCHEMA_VERSION
        is a ceiling, never a claim — an engine may declare a version ahead of
        its MIGRATIONS, and registering that version would make a migration
        added later look already applied and silently skip it.

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
                # One transaction per migration. executescript() commits any
                # pending transaction before it starts and then runs the
                # script statement by statement, committing each one — so a
                # script that failed halfway left its earlier DDL applied
                # while the version stayed behind, and a retry of the same
                # non-idempotent DDL could never succeed. The transaction must
                # therefore live inside the script text; the rollback in the
                # handler below then unwinds the whole migration.
                conn.executescript(f"BEGIN;\n{self.MIGRATIONS[version]}\nCOMMIT;")
                applied += 1
            # Registry and user_version must agree, and neither may claim a
            # schema newer than the migrations actually applied. Writing the
            # row before the clamp pinned the registry at the highest applied
            # migration (1) while user_version was raised to SCHEMA_VERSION
            # (3), so the two disagreed and the registry stayed at 1 forever.
            # Clamping the row UP to SCHEMA_VERSION would be worse the other
            # way: an engine whose SCHEMA_VERSION runs ahead of its
            # MIGRATIONS would register as current and skip the migration
            # added later. So SCHEMA_VERSION is a ceiling here, and the row
            # gets the final value that is written.
            registered = max([*pending, row[0] if row else 0])
            registered = min(registered, self.SCHEMA_VERSION)
            conn.execute(
                "INSERT OR REPLACE INTO _purr_schema (engine, version) VALUES (?, ?)",
                (engine, registered),
            )
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
            conn = sqlite3.connect(str(self._db_path))
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            # Explicit writer-wait contract: do not rely on the driver default.
            conn.execute(f"PRAGMA busy_timeout={self.BUSY_TIMEOUT_MS}")
            # 16 MB page cache (was 2 MB), 256 MB address-space mapping (was 0,
            # i.e. every read copied pages through a syscall), temp tables and
            # sorts in memory (was file-backed), and WAL capped at 64 MB (was
            # unbounded, -1) so a long write burst cannot grow the -wal
            # sidecar without limit.
            conn.execute("PRAGMA cache_size=-16000")
            conn.execute("PRAGMA mmap_size=268435456")
            conn.execute("PRAGMA temp_store=MEMORY")
            conn.execute("PRAGMA journal_size_limit=67108864")
            # SQLite's LIKE folds ASCII case by default; keys() promises Redis
            # KEYS semantics, where 'USER:*' must not match 'user:1'.
            conn.execute("PRAGMA case_sensitive_like=ON")
            conn.row_factory = sqlite3.Row
            # Orphan rows predate FK enforcement: remove them first, while the
            # constraint is still off, then turn enforcement on.
            self._cleanup_orphans(conn)
            self._enable_foreign_keys(conn)
            self._local.conn = conn
        return self._local.conn

    @staticmethod
    def _quote(identifier: str) -> str:
        return '"' + identifier.replace('"', '""') + '"'

    def _foreign_keys(self, conn: sqlite3.Connection) -> list[tuple[str, str, str, str]]:
        """Every declared FK in the file: (child table, child col, parent, col).

        Read from the schemas themselves (PRAGMA foreign_key_list) so the
        backend needs no knowledge of which engine owns which table. SQLite
        reports `to` as NULL when the FK targets the parent's primary key;
        `PRAGMA table_info` resolves that column.
        """
        tables = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )
        ]
        found: list[tuple[str, str, str, str]] = []
        for table in tables:
            for fk in conn.execute(f"PRAGMA foreign_key_list({self._quote(table)})"):
                parent, child_col, parent_col = fk[2], fk[3], fk[4]
                if not parent_col:
                    parent_col = next(
                        (
                            col[1]
                            for col in conn.execute(f"PRAGMA table_info({self._quote(parent)})")
                            if col[5]
                        ),
                        None,
                    )
                if parent_col:
                    found.append((table, child_col, parent, parent_col))
        return found

    def _cleanup_orphans(self, conn: sqlite3.Connection) -> int:
        """Delete child rows whose FK parent is missing. Returns the count.

        A database written before enforcement was on can hold orphans. They
        are invisible to the constraint, but every later write that touches
        the parent's key then fails with "FOREIGN KEY constraint failed", so
        they must go before the pragma is enabled. The probe runs first and is
        read-only: opening must not need the write lock (a second instance
        opens while another holds BEGIN IMMEDIATE).
        """
        removed = 0
        for table, child_col, parent, parent_col in self._foreign_keys(conn):
            child = self._quote(table)
            orphans = (
                f"{self._quote(child_col)} IS NOT NULL AND NOT EXISTS"
                f" (SELECT 1 FROM {self._quote(parent)} AS p"
                f" WHERE p.{self._quote(parent_col)} = {child}.{self._quote(child_col)})"
            )
            if conn.execute(f"SELECT 1 FROM {child} WHERE {orphans}").fetchone() is None:
                continue
            cur = conn.execute(f"DELETE FROM {child} WHERE {orphans}")
            removed += cur.rowcount
            conn.commit()
        return removed

    def _enable_foreign_keys(self, conn: sqlite3.Connection) -> None:
        """Turn FK enforcement on, verified by reading the pragma back.

        `PRAGMA foreign_keys` is silently ignored inside a transaction, so it
        runs before any DDL/DML on a connection with nothing open, and the
        read-back proves the setting took instead of trusting the call. If it
        did not, the open transaction is abandoned and it is retried once.
        """
        if conn.in_transaction:
            conn.commit()
        conn.execute("PRAGMA foreign_keys=ON")
        if not conn.execute("PRAGMA foreign_keys").fetchone()[0]:
            conn.rollback()
            conn.execute("PRAGMA foreign_keys=ON")

    def close(self) -> None:
        """Close the connection for this thread and reset its per-thread state.

        The transaction flag and the journal buffer live in threading.local
        and outlive the connection. Closing while a transaction is open used
        to leave in_txn=True behind, so every later transaction() on that
        thread failed with "nested transaction() is not supported" forever.
        Attrs are reset even when there is no connection to close, so a second
        close() is harmless.

        Only the calling thread is reset: other threads keep their own
        connections, transaction flags and buffers.
        """
        if hasattr(self._local, "conn") and self._local.conn is not None:
            with contextlib.suppress(Exception):
                self._local.conn.close()
        self._local.conn = None
        self._local.in_txn = False
        self._local.journal_buffer = []

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
