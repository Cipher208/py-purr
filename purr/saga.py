"""PURR Saga — compensating transactions for multi-step operations.

Extracted from an internal agent core.
Removed project-specific event types, kept core saga pattern.
"""

from __future__ import annotations

import contextlib
import copy
import json
import threading
from collections.abc import Callable, Coroutine
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .backend import SQLiteBackend


class SagaStatus(StrEnum):
    """Lifecycle states of a saga execution."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    COMPENSATING = "compensating"
    COMPENSATED = "compensated"


class SagaStep(BaseModel):
    """A step in a saga."""

    name: str
    action: Callable[[dict[str, Any]], Coroutine[Any, Any, dict[str, Any]]]
    compensation: Callable[[dict[str, Any]], Coroutine[Any, Any, None]] | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    status: SagaStatus = SagaStatus.PENDING
    result: dict[str, Any] = Field(default_factory=dict)
    written: list[str] = Field(default_factory=list)
    # Previous values of `written` keys that existed before the step ran.
    # Keys absent from this mapping were added by the step and are removed
    # on rollback instead of restored.
    restore: dict[str, Any] = Field(default_factory=dict)


def _unchanged(old: Any, new: Any) -> bool:
    """Compare two values, treating an uncomparable pair as changed.

    Array-likes (numpy.ndarray, pandas.Series) return a non-bool from `==`,
    so `bool()` raises; such keys must be tracked, not crash the step.
    """
    try:
        return bool(old == new)
    except Exception:
        return False


class Saga(SQLiteBackend):
    """Saga pattern for distributed transactions.

    Executes steps sequentially. If any step fails, compensates
    previously completed steps in reverse order and rolls back the
    data each one touched: added keys are removed, overwritten or
    deleted keys are restored to their previous values.

    Rollback covers previously completed steps only; the failed
    step's own compensation must be handled by the action itself.

    The saga is in-memory unless db_path is given. With db_path a checkpoint
    (name, status, current_step, data) is written to the shared SQLite file
    on every step and at completion; no automatic resume is performed.
    """

    ENGINE_NAME = "saga"
    SCHEMA_VERSION = 1
    MIGRATIONS = {
        1: """
            CREATE TABLE IF NOT EXISTS saga_state (
                name TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                current_step INTEGER NOT NULL,
                data TEXT NOT NULL DEFAULT '{}'
            );
            """,
    }

    def _init_db(self) -> None:
        self.run_migrations()

    def __init__(self, name: str, db_path: str | Path | None = None) -> None:
        self.name = name
        self._steps: list[SagaStep] = []
        self._status = SagaStatus.PENDING
        self._data: dict[str, Any] = {}
        self._current_step = 0
        if db_path is None:
            # Keep the backend unopened: Saga(name) stays purely in memory.
            self._local = threading.local()
            self._db_path = None
        else:
            super().__init__(db_path)

    @property
    def status(self) -> SagaStatus:
        """Current execution status of the saga."""
        return self._status

    @property
    def data(self) -> dict[str, Any]:
        """Working data accumulated by completed steps."""
        return self._data

    def add_step(
        self,
        name: str,
        action: Callable[[dict[str, Any]], Coroutine[Any, Any, dict[str, Any]]],
        compensation: Callable[[dict[str, Any]], Coroutine[Any, Any, None]] | None = None,
    ) -> Saga:
        """Add a step with optional compensation."""
        self._steps.append(SagaStep(name=name, action=action, compensation=compensation))
        return self

    async def execute(self, initial_data: dict[str, Any] | None = None) -> dict[str, Any]:
        """Execute all steps. Compensate on failure."""
        self._data = initial_data or {}
        self._status = SagaStatus.RUNNING
        self._current_step = 0
        # Reset per-step state so a re-executed saga does not fire
        # compensations from a previous run.
        for step in self._steps:
            step.status = SagaStatus.PENDING
            step.result = {}
            step.written = []
            step.restore = {}

        try:
            for i, step in enumerate(self._steps):
                self._current_step = i
                step.status = SagaStatus.RUNNING
                # Written BEFORE the action: a process dying inside the step
                # still leaves a non-completed checkpoint in the shared file.
                self._write_checkpoint()

                try:
                    # Deep copy: in-place mutations of nested values must be
                    # invisible in the snapshot, or they cannot be rolled back.
                    snapshot = copy.deepcopy(self._data)
                    step.result = await step.action(self._data)
                    self._data.update(step.result)
                    # Keys this step touched (added, changed or deleted) and
                    # the values they had before the step — rolled back in
                    # reverse order if the step is compensated later.
                    step.written = []
                    step.restore = {}
                    for key in [*self._data, *(k for k in snapshot if k not in self._data)]:
                        if key not in snapshot:
                            step.written.append(key)  # added by the step
                        elif key not in self._data or not _unchanged(
                            snapshot[key], self._data[key]
                        ):
                            step.written.append(key)  # changed or deleted
                            step.restore[key] = snapshot[key]
                    step.status = SagaStatus.COMPLETED
                    step.data = self._data.copy()

                except Exception:
                    step.status = SagaStatus.FAILED
                    await self._compensate(i)
                    raise

            self._status = SagaStatus.COMPLETED
            self._write_checkpoint()
            return self._data

        except Exception:
            if self._status != SagaStatus.COMPENSATED:
                self._status = SagaStatus.FAILED
            with contextlib.suppress(Exception):
                self._write_checkpoint()
            raise

    async def _compensate(self, failed_step: int) -> None:
        """Compensate completed steps in reverse order."""
        self._status = SagaStatus.COMPENSATING

        for i in range(failed_step - 1, -1, -1):
            step = self._steps[i]
            if step.status == SagaStatus.COMPLETED:
                if step.compensation:
                    # Compensation failed, continue with others
                    with contextlib.suppress(Exception):
                        await step.compensation(step.data)
                # Roll back the data written by the compensated step: restore
                # overwritten/deleted keys, drop keys the step added.
                for key in step.written:
                    if key in step.restore:
                        self._data[key] = step.restore[key]
                    else:
                        self._data.pop(key, None)

        self._status = SagaStatus.COMPENSATED

    def get_state(self) -> dict[str, Any]:
        """Get current saga state."""
        return {
            "name": self.name,
            "status": self._status.value,
            "current_step": self._current_step,
            "data": self._data,
            "steps": [
                {
                    "name": step.name,
                    "status": step.status.value,
                    "result": step.result,
                }
                for step in self._steps
            ],
        }

    def _write_checkpoint(self) -> None:
        """Upsert the visible slice after each transition; never a journal event."""
        if self._db_path is None:
            return
        try:
            payload = json.dumps(self._data, default=str)
        except (TypeError, ValueError, RecursionError):
            payload = "{}"
        conn = self._get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO saga_state (name, status, current_step, data)"
            " VALUES (?, ?, ?, ?)",
            (self.name, self._status.value, self._current_step, payload),
        )
        conn.commit()

    def load_persisted_state(self) -> dict[str, Any] | None:
        """Read this saga's checkpoint from the shared file, if one exists.

        Only name/status/current_step/data are persisted: actions, compensations
        and the write-tracking fields are not, so nothing here can be resumed.
        """
        if self._db_path is None:
            return None
        cursor = self._get_conn().execute(
            "SELECT name, status, current_step, data FROM saga_state WHERE name = ?",
            (self.name,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return {
            "name": row["name"],
            "status": row["status"],
            "current_step": row["current_step"],
            "data": json.loads(row["data"]),
        }
