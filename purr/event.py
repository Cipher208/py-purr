"""PURR Event — event types and bus for pub/sub."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Coroutine

from pydantic import BaseModel, Field


class EventType(str, Enum):
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
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    correlation_id: str | None = None
    version: int = 1
    source: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


EventHandler = Callable[[Event], Coroutine[Any, Any, None]]


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
            self._history = self._history[-self._max_history:]

        handlers = self._handlers.get(event.topic, [])
        wildcard_handlers = self._handlers.get("*", [])

        for handler in handlers + wildcard_handlers:
            try:
                await handler(event)
            except Exception:
                pass  # Don't let handler errors break the bus

    def publish_sync(self, event: Event) -> None:
        """Publish synchronously (for non-async contexts)."""
        self._history.append(event)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

    def get_history(self, topic: str | None = None, limit: int = 100) -> list[Event]:
        """Get event history."""
        events = self._history
        if topic:
            events = [e for e in events if e.topic == topic]
        return events[-limit:]

    def clear_history(self) -> None:
        """Clear event history."""
        self._history.clear()
