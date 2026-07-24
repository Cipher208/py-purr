"""PURR Middleware — event processing pipeline.

Extracted from an internal agent core.
Generic middleware for any event-based system.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable, Coroutine

from .event import Event

MiddlewareNext = Callable[[Event], Coroutine[Any, Any, None]]


class Middleware(ABC):
    """Base middleware class."""

    @abstractmethod
    async def process(self, event: Event, next: MiddlewareNext) -> None:
        ...


class LoggingMiddleware(Middleware):
    """Logs events."""

    def __init__(self, logger: Any | None = None) -> None:
        self._logger = logger

    async def process(self, event: Event, next: MiddlewareNext) -> None:
        msg = f"[{event.type.value}] {event.topic} id={event.id[:8]}"
        if event.correlation_id:
            msg += f" corr={event.correlation_id[:8]}"
        if self._logger:
            self._logger.info(msg)
        else:
            print(msg)
        await next(event)


class RateLimitMiddleware(Middleware):
    """Rate limits events using token bucket."""

    def __init__(
        self,
        max_per_second: float = 10.0,
        max_burst: int = 20,
    ) -> None:
        self._max_per_second = max_per_second
        self._max_burst = max_burst
        self._tokens = float(max_burst)
        self._last_refill = 0.0

    async def process(self, event: Event, next: MiddlewareNext) -> None:
        import time

        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(
            self._max_burst,
            self._tokens + elapsed * self._max_per_second,
        )
        self._last_refill = now

        if self._tokens < 1.0:
            return

        self._tokens -= 1.0
        await next(event)


class DedupMiddleware(Middleware):
    """Deduplicates events by ID."""

    def __init__(self, max_size: int = 10000, ttl_seconds: float = 300.0) -> None:
        self._seen: dict[str, float] = {}
        self._max_size = max_size
        self._ttl = ttl_seconds

    async def process(self, event: Event, next: MiddlewareNext) -> None:
        import time

        now = time.monotonic()
        self._evict(now)

        if event.id in self._seen:
            return

        self._seen[event.id] = now
        await next(event)

    def _evict(self, now: float) -> None:
        if len(self._seen) > self._max_size:
            expired = [k for k, v in self._seen.items() if now - v > self._ttl]
            for k in expired:
                del self._seen[k]

            if len(self._seen) > self._max_size:
                oldest = sorted(self._seen, key=self._seen.get)[: self._max_size // 2]
                for k in oldest:
                    del self._seen[k]


class FilterMiddleware(Middleware):
    """Filters events by topic or type."""

    def __init__(
        self,
        allowed_topics: list[str] | None = None,
        blocked_topics: list[str] | None = None,
        allowed_types: list[str] | None = None,
    ) -> None:
        self._allowed_topics = set(allowed_topics) if allowed_topics else None
        self._blocked_topics = set(blocked_topics) if blocked_topics else set()
        self._allowed_types = set(allowed_types) if allowed_types else None

    async def process(self, event: Event, next: MiddlewareNext) -> None:
        if self._allowed_topics and event.topic not in self._allowed_topics:
            return
        if event.topic in self._blocked_topics:
            return
        if self._allowed_types and event.type.value not in self._allowed_types:
            return
        await next(event)


class TransformMiddleware(Middleware):
    """Transforms events before passing to next."""

    def __init__(self, transformer: Callable[[Event], Event] | None = None) -> None:
        self._transformer = transformer

    async def process(self, event: Event, next: MiddlewareNext) -> None:
        if self._transformer:
            event = self._transformer(event)
        await next(event)


class MiddlewarePipeline:
    """Chain of middleware to process events."""

    def __init__(self) -> None:
        self._middlewares: list[Middleware] = []

    def add(self, middleware: Middleware) -> None:
        """Add middleware to the pipeline."""
        self._middlewares.append(middleware)

    async def execute(self, event: Event, handler: MiddlewareNext) -> None:
        """Execute the pipeline with the given event and final handler."""
        chain = handler

        for middleware in reversed(self._middlewares):
            next_chain = chain

            async def make_chain(m: Middleware, n: MiddlewareNext) -> MiddlewareNext:
                async def chain(e: Event) -> None:
                    await m.process(e, n)

                return chain

            chain = await make_chain(middleware, next_chain)

        await chain(event)
