"""PURR Saga — compensating transactions for multi-step operations.

Extracted from an internal agent core.
Removed project-specific event types, kept core saga pattern.
"""

from __future__ import annotations

import contextlib
import copy
from collections.abc import Callable, Coroutine
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


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


class Saga:
    """Saga pattern for distributed transactions.

    Executes steps sequentially. If any step fails, compensates
    previously completed steps in reverse order and rolls back the
    data each one touched: added keys are removed, overwritten or
    deleted keys are restored to their previous values.

    Rollback covers previously completed steps only; the failed
    step's own compensation must be handled by the action itself.

    The saga is in-memory: if the process dies, all state is lost.
    """

    def __init__(self, name: str) -> None:
        self.name = name
        self._steps: list[SagaStep] = []
        self._status = SagaStatus.PENDING
        self._data: dict[str, Any] = {}
        self._current_step = 0

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
            return self._data

        except Exception:
            if self._status != SagaStatus.COMPENSATED:
                self._status = SagaStatus.FAILED
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
