"""PURR Event — event types and bus for pub/sub."""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class EventType(StrEnum):
    """Event types."""

    STATE = "state"
    STORE = "store"
    SAGA = "saga"
    ERROR = "error"
    SYSTEM = "system"


class Event(BaseModel):
    """An event in the system."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    type: EventType
    topic: str
    payload: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    correlation_id: str | None = None
    version: int = 1
    source: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


EventHandler = Callable[[Event], Coroutine[Any, Any, None]]
"""Async handler. Sync handlers (plain functions returning a non-awaitable)
are also accepted by subscribe() and dispatched directly."""


class EventBus:
    """Simple pub/sub event bus."""

    def __init__(self) -> None:
        self._handlers: dict[str, list[EventHandler]] = {}
        self._history: list[Event] = []
        self._max_history = 1000

    def subscribe(self, topic: str, handler: EventHandler) -> None:
        """Subscribe to a topic."""
        if topic not in self._handlers:
            self._handlers[topic] = []
        self._handlers[topic].append(handler)

    def unsubscribe(self, topic: str, handler: EventHandler) -> None:
        """Unsubscribe from a topic."""
        if topic in self._handlers:
            self._handlers[topic] = [h for h in self._handlers[topic] if h != handler]

    async def publish(self, event: Event) -> None:
        """Publish an event to all subscribers."""
        self._history.append(event)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history :]

        handlers = self._handlers.get(event.topic, [])
        wildcard_handlers = self._handlers.get("*", [])

        for handler in handlers + wildcard_handlers:
            # Don't let handler errors break the bus
            with contextlib.suppress(Exception):
                await handler(event)

    def publish_sync(self, event: Event) -> None:
        """Publish synchronously (for non-async contexts).

        Sync handlers are invoked directly. Async handlers are executed via
        asyncio.run() — allowed only when no event loop is running; calling
        publish_sync with async handlers inside a running loop raises
        RuntimeError("use await bus.publish() inside async context").
        Handler exceptions are suppressed, matching async publish().
        """
        self._history.append(event)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history :]

        handlers = self._handlers.get(event.topic, [])
        wildcard_handlers = self._handlers.get("*", [])

        coros: list[Coroutine[Any, Any, None]] = []
        for handler in handlers + wildcard_handlers:
            # Don't let handler errors break the bus
            with contextlib.suppress(Exception):
                result = handler(event)
                if result is not None and hasattr(result, "__await__"):
                    coros.append(result)

        if not coros:
            return

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            for coro in coros:
                with contextlib.suppress(Exception):
                    asyncio.run(coro)
        else:
            for coro in coros:
                coro.close()
            raise RuntimeError("use await bus.publish() inside async context")

    def get_history(self, topic: str | None = None, limit: int = 100) -> list[Event]:
        """Get event history."""
        events = self._history
        if topic:
            events = [e for e in events if e.topic == topic]
        return events[-limit:]

    def clear_history(self) -> None:
        """Clear event history."""
        self._history.clear()
