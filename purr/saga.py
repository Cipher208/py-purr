"""PURR Saga — compensating transactions for multi-step operations.

Extracted from an internal agent core.
Removed project-specific event types, kept core saga pattern.
"""

from __future__ import annotations

import asyncio
from enum import Enum
from typing import Any, Callable, Coroutine

from pydantic import BaseModel, Field


class SagaStatus(str, Enum):
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


class Saga:
    """Saga pattern for distributed transactions.

    Executes steps sequentially. If any step fails, compensates
    previously completed steps in reverse order.
    """

    def __init__(self, name: str) -> None:
        self.name = name
        self._steps: list[SagaStep] = []
        self._status = SagaStatus.PENDING
        self._data: dict[str, Any] = {}
        self._current_step = 0

    @property
    def status(self) -> SagaStatus:
        return self._status

    @property
    def data(self) -> dict[str, Any]:
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

        try:
            for i, step in enumerate(self._steps):
                self._current_step = i
                step.status = SagaStatus.RUNNING

                try:
                    step.result = await step.action(self._data)
                    self._data.update(step.result)
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
            if step.status == SagaStatus.COMPLETED and step.compensation:
                try:
                    await step.compensation(step.data)
                except Exception:
                    pass  # Compensation failed, continue with others

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
