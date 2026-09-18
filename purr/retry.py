"""PURR Retry — retry handler with exponential backoff.

Extracted from an internal agent core.
Generic retry logic for async operations.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any


@dataclass
class RetryConfig:
    """Retry configuration."""

    max_retries: int = 3
    base_delay: float = 1.0
    max_delay: float = 60.0
    exponential_base: float = 2.0
    jitter: bool = True


@dataclass
class RetryState:
    """Current retry state."""

    attempt: int = 0
    last_error: str = ""
    next_retry_at: float = 0.0


class RetryHandler:
    """Retry handler with exponential backoff."""

    def __init__(self, config: RetryConfig | None = None) -> None:
        self._config = config or RetryConfig()
        self._pending: dict[str, RetryState] = {}

    async def execute(
        self,
        func: Callable[..., Coroutine[Any, Any, Any]],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Execute a function with retries."""
        state = RetryState()

        while state.attempt <= self._config.max_retries:
            try:
                result = await func(*args, **kwargs)
                return result

            except Exception as e:
                state.attempt += 1
                state.last_error = str(e)

                if state.attempt > self._config.max_retries:
                    raise

                delay = self._calculate_delay(state.attempt)
                state.next_retry_at = asyncio.get_event_loop().time() + delay
                await asyncio.sleep(delay)

    def _calculate_delay(self, attempt: int) -> float:
        """Calculate delay with exponential backoff and jitter."""
        delay = self._config.base_delay * (self._config.exponential_base ** (attempt - 1))
        delay = min(delay, self._config.max_delay)
        if self._config.jitter:
            delay *= 0.5 + random.random()
        return delay
