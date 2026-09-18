"""Middleware contract: dedup, rate-limit, pipeline chain (Task 2)."""
import asyncio

from purr.event import Event, EventType
from purr.middleware import DedupMiddleware, MiddlewarePipeline, RateLimitMiddleware


def _ev(topic="t"):
    return Event(type=EventType.SYSTEM, topic=topic, payload={})


def _recorder(seen):
    async def rec(event):
        seen.append(event)

    return rec


def test_dedup_suppresses_same_id():
    async def go():
        pipe = MiddlewarePipeline()
        pipe.add(DedupMiddleware())
        seen = []
        ev = _ev()
        await pipe.execute(ev, _recorder(seen))
        await pipe.execute(ev, _recorder(seen))
        return seen

    assert len(asyncio.run(go())) == 1


def test_rate_limit_burst_then_drops():
    async def go():
        pipe = MiddlewarePipeline()
        pipe.add(RateLimitMiddleware(max_per_second=1, max_burst=1))
        seen = []
        for _ in range(3):
            await pipe.execute(_ev(), _recorder(seen))
        return seen

    assert len(asyncio.run(go())) == 1


def test_pipeline_chains_in_order():
    async def go():
        pipe = MiddlewarePipeline()
        order = []

        from purr.middleware import Middleware

        class Tag(Middleware):
            def __init__(self, name):
                self._name = name

            async def process(self, event, next):
                order.append(self._name)
                await next(event)

        pipe.add(Tag("first"))
        pipe.add(Tag("second"))
        await pipe.execute(_ev(), _recorder(order))
        return order

    result = asyncio.run(go())
    assert result[:2] == ["first", "second"]
    assert isinstance(result[2], Event)
