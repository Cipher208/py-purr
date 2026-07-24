"""PURR — Redis-like on SQLite.

A lightweight, thread-safe key-value store with:
- SQLite WAL for concurrent reads
- Atomic writes
- TTL support
- State machine with persistence
- Sagas for multi-step transactions
- Middleware pipeline
- Event bus for pub/sub
- Event stream with cursors (Redis Streams-like)
- Health monitoring
- Event schema versioning
- Retry with exponential backoff
"""

from .event import Event, EventBus, EventType
from .event_stream import EventStream
from .health import HealthChecker, HealthStatus
from .middleware import (
    DedupMiddleware,
    FilterMiddleware,
    LoggingMiddleware,
    Middleware,
    MiddlewarePipeline,
    RateLimitMiddleware,
    TransformMiddleware,
)
from .retry import RetryConfig, RetryHandler
from .saga import Saga, SagaStatus
from .state_machine import State, StateMachine, Transition
from .store import Store
from .versioning import EventVersioner

__version__ = "0.1.0"

__all__ = [
    "Store",
    "StateMachine",
    "State",
    "Transition",
    "Saga",
    "SagaStatus",
    "EventBus",
    "Event",
    "EventType",
    "EventStream",
    "EventVersioner",
    "HealthChecker",
    "HealthStatus",
    "Middleware",
    "MiddlewarePipeline",
    "LoggingMiddleware",
    "RateLimitMiddleware",
    "DedupMiddleware",
    "FilterMiddleware",
    "TransformMiddleware",
    "RetryHandler",
    "RetryConfig",
]
