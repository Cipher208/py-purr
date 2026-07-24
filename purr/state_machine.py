"""PURR State Machine — finite state machine with SQLite persistence.

Extracted from an internal agent core.
Removed project-specific states, kept core FSM functionality.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, Field


class State(BaseModel):
    """A state in the machine."""

    name: str
    data: dict[str, Any] = {}
    entered_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = {}


class Transition(BaseModel):
    """A transition between states."""

    source: str
    target: str
    event: str
    guard: Callable[[State, dict[str, Any]], bool] | None = None
    action: Callable[[State, dict[str, Any]], dict[str, Any]] | None = None


class StateMachine:
    """Finite state machine with SQLite WAL persistence.

    Features:
    - Thread-safe (threading.local connections)
    - WAL mode for concurrent reads
    - Atomic writes via INSERT OR REPLACE
    - Snapshots for rollback
    - Guard conditions and actions on transitions
    - on_enter/on_exit callbacks
    """

    def __init__(
        self,
        name: str,
        db_path: str | Path = "state.db",
    ) -> None:
        self.name = name
        self._db_path = Path(db_path)
        self._local = threading.local()
        self._transitions: list[Transition] = []
        self._on_enter: dict[str, Callable[[State], None]] = {}
        self._on_exit: dict[str, Callable[[State], None]] = {}
        self._current: State | None = None
        self._init_db()
        self._load_state()

    def _get_conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(str(self._db_path))
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.execute("PRAGMA synchronous=NORMAL")
            self._local.conn.row_factory = sqlite3.Row
        return self._local.conn

    def _init_db(self) -> None:
        conn = self._get_conn()
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS state_machines (
                name TEXT PRIMARY KEY,
                current_state TEXT NOT NULL,
                state_data TEXT NOT NULL DEFAULT '{}',
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS state_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                machine_name TEXT NOT NULL,
                state TEXT NOT NULL,
                data TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                FOREIGN KEY (machine_name) REFERENCES state_machines(name)
            );
            """
        )
        conn.commit()

    def add_transition(
        self,
        source: str,
        target: str,
        event: str,
        guard: Callable[[State, dict[str, Any]], bool] | None = None,
        action: Callable[[State, dict[str, Any]], dict[str, Any]] | None = None,
    ) -> None:
        """Add a transition rule."""
        self._transitions.append(
            Transition(source=source, target=target, event=event, guard=guard, action=action)
        )

    def on_enter(self, state_name: str, callback: Callable[[State], None]) -> None:
        """Register callback for state entry."""
        self._on_enter[state_name] = callback

    def on_exit(self, state_name: str, callback: Callable[[State], None]) -> None:
        """Register callback for state exit."""
        self._on_exit[state_name] = callback

    @property
    def current_state(self) -> str | None:
        return self._current.name if self._current else None

    @property
    def state_data(self) -> dict[str, Any]:
        return self._current.data if self._current else {}

    def send(self, event: str, data: dict[str, Any] | None = None) -> bool:
        """Send an event to trigger a transition.

        Returns True if transition occurred, False otherwise.
        """
        if not self._current:
            return False

        data = data or {}
        for transition in self._transitions:
            if transition.source == self._current.name and transition.event == event:
                if transition.guard and not transition.guard(self._current, data):
                    continue

                old_state = self._current

                if transition.action:
                    data = transition.action(self._current, data)

                if old_state.name in self._on_exit:
                    self._on_exit[old_state.name](old_state)

                new_state = State(
                    name=transition.target,
                    data={**old_state.data, **data},
                )
                self._current = new_state
                self._save_state()

                if new_state.name in self._on_enter:
                    self._on_enter[new_state.name](new_state)

                return True
        return False

    def set_state(self, name: str, data: dict[str, Any] | None = None) -> None:
        """Force set state (bypasses transitions)."""
        self._current = State(name=name, data=data or {})
        self._save_state()

    def snapshot(self) -> None:
        """Save current state as a snapshot."""
        if not self._current:
            return

        conn = self._get_conn()
        conn.execute(
            """
            INSERT INTO state_snapshots (machine_name, state, data, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                self.name,
                self._current.name,
                json.dumps(self._current.data),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()

    def restore_snapshot(self, snapshot_id: int | None = None) -> bool:
        """Restore from a snapshot. If no ID, restore latest."""
        conn = self._get_conn()
        if snapshot_id:
            row = conn.execute(
                "SELECT * FROM state_snapshots WHERE id = ? AND machine_name = ?",
                (snapshot_id, self.name),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM state_snapshots WHERE machine_name = ? ORDER BY id DESC LIMIT 1",
                (self.name,),
            ).fetchone()

        if not row:
            return False

        self._current = State(
            name=row["state"],
            data=json.loads(row["data"]),
            entered_at=datetime.fromisoformat(row["created_at"]),
        )
        self._save_state()
        return True

    def get_snapshots(self, limit: int = 10) -> list[dict[str, Any]]:
        """Get recent snapshots."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM state_snapshots WHERE machine_name = ? ORDER BY id DESC LIMIT ?",
            (self.name, limit),
        ).fetchall()
        return [
            {
                "id": row["id"],
                "state": row["state"],
                "data": json.loads(row["data"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def _load_state(self) -> None:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM state_machines WHERE name = ?", (self.name,)
        ).fetchone()
        if row:
            self._current = State(
                name=row["current_state"],
                data=json.loads(row["state_data"]),
                entered_at=datetime.fromisoformat(row["updated_at"]),
            )

    def _save_state(self) -> None:
        if not self._current:
            return

        conn = self._get_conn()
        conn.execute(
            """
            INSERT OR REPLACE INTO state_machines (name, current_state, state_data, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                self.name,
                self._current.name,
                json.dumps(self._current.data),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()

    def close(self) -> None:
        """Close the connection for this thread."""
        if hasattr(self._local, "conn") and self._local.conn is not None:
            try:
                self._local.conn.close()
            except Exception:
                pass
            self._local.conn = None
