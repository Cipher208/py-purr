"""PURR Event — event types and bus for pub/sub."""

from __future__ import annotations

import asyncio
import contextlib
import inspect
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


async def _await_result(result: Any) -> None:
    """Await an arbitrary awaitable — asyncio.run() accepts only coroutines."""
    await result


class EventBus:
    """Simple pub/sub event bus.

    Args:
        on_handler_error: Optional callback ``(event, exception) -> None``
            invoked when a subscriber handler raises. By default (None)
            handler exceptions stay silent, matching the historical
            behavior. Exceptions raised by the callback itself are
            swallowed so the dispatcher never breaks.
    """

    def __init__(
        self, on_handler_error: Callable[[Event, BaseException], None] | None = None
    ) -> None:
        self._handlers: dict[str, list[EventHandler]] = {}
        self._history: list[Event] = []
        self._max_history = 1000
        self.on_handler_error = on_handler_error

    def _call_error_callback(self, event: Event, exc: BaseException) -> Any:
        """Invoke on_handler_error, swallowing its own failures."""
        if self.on_handler_error is None:
            return None
        # a broken error callback must not break the dispatcher
        try:
            return self.on_handler_error(event, exc)
        except Exception:
            return None

    def _report_handler_error(self, event: Event, exc: BaseException) -> None:
        """Report a handler error from synchronous code.

        An async on_handler_error is executed with asyncio.run() when no loop
        is running. Inside a running loop it cannot be awaited from here, so
        the coroutine is closed — the error was already lost, but at least it
        no longer emits a "coroutine was never awaited" RuntimeWarning. The
        async path (publish) awaits such a callback instead.
        """
        result = self._call_error_callback(event, exc)
        if not inspect.iscoroutine(result):
            return
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            with contextlib.suppress(Exception):
                asyncio.run(result)
        else:
            result.close()

    async def _report_handler_error_async(self, event: Event, exc: BaseException) -> None:
        """Report a handler error from publish(): await an async callback."""
        result = self._call_error_callback(event, exc)
        if inspect.isawaitable(result):
            with contextlib.suppress(Exception):
                await result

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
            try:
                await handler(event)
            except Exception as exc:
                await self._report_handler_error_async(event, exc)

    def publish_sync(self, event: Event) -> None:
        """Publish synchronously (for non-async contexts).

        Delivery order is subscription order (event handlers, then "*"
        wildcard handlers). Sync handlers are invoked directly; ``async def``
        handlers are executed with asyncio.run() at their own position in
        that order, so mixing both kinds does not reorder delivery.

        With a running event loop and at least one async handler this raises
        RuntimeError("use await bus.publish() inside async context") before
        ANY handler is called: the call cannot deliver the async part, and
        running the sync handlers first left their side effects behind an
        exception. Async handlers are recognised by
        inspect.iscoroutinefunction; a plain function that *returns* an
        awaitable cannot be recognised before being called, so it is treated
        as sync (it runs; its awaitable is executed too since no loop is
        running).

        Handler exceptions are suppressed, matching async publish().
        """
        self._history.append(event)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history :]

        handlers = self._handlers.get(event.topic, []) + self._handlers.get("*", [])

        if any(inspect.iscoroutinefunction(handler) for handler in handlers):
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                pass
            else:
                raise RuntimeError("use await bus.publish() inside async context")

        for handler in handlers:
            # Don't let handler errors break the bus
            try:
                if inspect.iscoroutinefunction(handler):
                    asyncio.run(handler(event))
                    continue
                result = handler(event)
                if inspect.isawaitable(result):
                    # Edge: sync callable that returned an awaitable. No loop
                    # is running here, so run it like an async handler.
                    asyncio.run(_await_result(result))
            except Exception as exc:
                self._report_handler_error(event, exc)

    def get_history(self, topic: str | None = None, limit: int = 100) -> list[Event]:
        """Get event history."""
        events = self._history
        if topic:
            events = [e for e in events if e.topic == topic]
        return events[-limit:]

    def clear_history(self) -> None:
        """Clear event history."""
        self._history.clear()
